import json
import logging
import sys
import time

from flask import Flask, g, render_template, request, make_response, jsonify
from flask import redirect, url_for
import redis

sys.stdout = sys.stderr
MAX_SAVED = 100
DEFAULT_CONF = {'wheartbeat': 10, 'eheartbeat': 20, 'labels': []}
app = Flask(__name__)
pool = redis.ConnectionPool(host='localhost', port=6379, db=0)


def get_ts():
    if app.config.get('TESTING'):
        return app.config['TESTING_TS']
    return int(time.time())


def init_db():
    r = conn()
    r.flushdb()


def conn():
    r = redis.StrictRedis(connection_pool=pool)
    return r


def chunks(l, n):
    """ Yield successive n-sized chunks from l.
    """
    for i in xrange(0, len(l), n):
        yield l[i:i + n]


@app.before_request
def before_request():
    g.db = conn()


def get_old_conf(sid):
    conf = g.db.hget("lb:s:%s" % sid, "conf")
    if not conf:
        return dict(DEFAULT_CONF)
    return json.loads(conf)


def update_labels(pipe, sid, old_lbls, new_lbls):
    pipe.sadd("lb:services:all", sid)
    for lbl in new_lbls - old_lbls:
        pipe.sadd("lb:services:%s" % lbl, sid)
        pipe.sadd("lb:labels", lbl)
    for lbl in old_lbls - new_lbls:
        pipe.srem("lb:services:%s" % lbl, sid)


@app.route("/s/<sid>/unmaint", methods = ["GET", "POST"])
def unmaint(sid):
    conf = get_old_conf(sid)
    if 'maint' in conf:
        del conf['maint']
    g.db.hset("lb:s:%s" % sid, "conf", json.dumps(conf))
    if request.json:
        return jsonify()
    return "ok\n"


@app.route("/s/<sid>/maint", methods = ["GET", "POST"])
def maint(sid):
    type = "soft"
    expiry = 10 * 60
    if request.json:
        type = request.json.get('type', type)
        expiry = int(request.json.get('expiry'), expiry)
        do_maint(sid, type, expiry)
        return jsonify()
    elif request.form:
        type = request.form.get('type', type)
        expiry = int(request.form.get('expiry', expiry))
    do_maint(sid, type, expiry)
    return "ok\n"


def do_maint(sid, type, expiry):
    now = get_ts()
    conf = get_old_conf(sid)
    conf['maint'] = {'type': type,
                     'expiry': now + expiry}
    g.db.hset("lb:s:%s" % sid, "conf", json.dumps(conf))


@app.route("/s/<sid>/delete", methods = ["POST"])
def delete(sid):
    conf = get_old_conf(sid)
    lbls = set(conf.get('labels', []))
    lbls.add('all')
    with g.db.pipeline() as pipe:
        for lbl in lbls:
            pipe.srem("lb:services:%s" % lbl, sid)
        pipe.delete("lb:s:%s" % sid)
        pipe.delete("lb:s:%s:h" % sid)
        pipe.execute()
    if request.json:
        return jsonify()
    return "ok\n"


@app.route("/s/<sid>", methods = ["GET", "POST"])
def trigger_ind(sid):
    return trigger(sid)


@app.route("/s/<sid>/trigger", methods = ["GET", "POST"])
def trigger(sid):
    if request.json:
        whb = request.json.get('heartbeat', {}).get('warning')
        ehb = request.json.get('heartbeat', {}).get('error')
        do_trigger(sid, request.json.get('labels', []),
                   whb, ehb)
        return jsonify()
    elif request.form:
        lbls = set([])
        if 'labels' in request.form:
            lbls = [l.strip() for l in request.form['labels'].split(',')]
            lbls = set([l for l in lbls if l])
        ehb = whb = None
        for key, value in request.form.items(multi=True):
            if key == 'heartbeat':
                if ':' in value:
                    type, value = value.split(":")
                else:
                    type, value = 'error', value
                if type == 'error':
                    ehb = int(value)
                elif type == 'warning':
                    whb = int(value)
        do_trigger(sid, lbls, whb, ehb)
        return "ok\n"
    do_trigger(sid, [], None, None)
    return "ok\n"


def do_trigger(sid, new_lbls = None, whb = None, ehb = None):
    now = get_ts()
    conf = get_old_conf(sid)
    new_lbls = set([l.lower() for l in new_lbls])
    old_lbls = set(conf.get('labels', []))
    if new_lbls:
        conf['labels'] = sorted(new_lbls)
    if ehb is not None or whb is not None:
        conf['eheartbeat'] = ehb
        conf['wheartbeat'] = whb
    if conf.get('maint', {}).get('type') == 'soft':
        del conf['maint']
    with g.db.pipeline() as pipe:
        update_labels(pipe, sid, old_lbls, new_lbls)
        pipe.hset("lb:s:%s" % sid, "last", '%d:1' % now)
        pipe.lpush("lb:s:%s:h" % sid, '%d:1' % now)
        pipe.ltrim("lb:s:%s:h" % sid, 0, MAX_SAVED - 1)
        if conf:
            pipe.hset("lb:s:%s" % sid, "conf", json.dumps(conf))
        pipe.execute()


@app.template_filter('pretty_interval')
def sago(i):
    s = ""
    if i == 0:
        return "now"
    if i >= 86400:
        s += "%dd" % int(i / 3600)
        i = i % 86400
    if i >= 3600:
        s += "%dh" % int(i / 3600)
        i = i % 3600
    if i >= 60:
        s += "%dm" % int(i / 60)
        i = i % 60
    # be restrictive when we show 'seconds'
    if s == "" and i > 0:
        s += "%ds" % i
    return s


def eval_service(conf, service, now):
    if conf.get('wheartbeat') and service['last_heartbeat'] >= conf['wheartbeat']:
        service['wheartbeat'] = True
        service['status'] = 'warning'
    if conf.get('eheartbeat') and service['last_heartbeat'] >= conf['eheartbeat']:
        service['eheartbeat'] = True
        service['status'] = 'error'
    if 'maint' in conf and conf['maint']['expiry'] >= now:
        service['status'] = 'maint'


def get_services(lbl):
    now = get_ts()
    fields = ("#", "lb:s:*->last", "lb:s:*->conf")
    services = []
    for sid, last, conf in \
            chunks(g.db.sort("lb:services:%s" % lbl, get=fields), 3):
        ts, lval = last.split(":")
        ts = int(ts)
        conf = json.loads(conf) if conf else dict(DEFAULT_CONF)
        service = {'sid': sid, 'ts': ts, 'status': 'ok',
                   'conf': conf,
                   'last_ts': ts, 'last_val': lval,
                   'last_heartbeat': now - ts}
        eval_service(conf, service, now)
        services.append(service)
    services.sort(lambda a, b: cmp(a['sid'], b['sid']))
    return services


@app.route("/dashboard/<lbl>/", methods = ["GET"])
def get_list(lbl):
    services = get_services(lbl)
    has_warnings = len([s for s in services if s['status'] == 'warning']) > 0
    has_errors = len([s for s in services if s['status'] == 'error']) > 0
    return render_template("dashboardui.html", services=services,
                           has_warnings=has_warnings,
                           has_errors=has_errors,
                           lbl=lbl)


@app.route("/dashboard/", methods = ["GET"])
def get_list_all():
    return redirect(url_for('.get_list', lbl='all'))


@app.route("/dashboard/<lbl>/raw", methods = ["GET"])
def get_list_raw(lbl):
    services = get_services(lbl)
    has_warnings = len([s for s in services if s['status'] == 'warning']) > 0
    has_errors = len([s for s in services if s['status'] == 'error']) > 0
    has_maint = len([s for s in services if s['status'] == 'maint']) > 0
    html = render_template("dashboard.html", services=services,
                           has_warnings=has_warnings,
                           has_errors=has_errors,
                           has_maint=has_maint)
    resp = make_response(html)
    resp.headers["Content-type"] = "text/plain"
    return resp


@app.route("/dashboard/<lbl>/json", methods = ["GET"])
def get_list_json(lbl):
    services = get_services(lbl)
    return jsonify(services=services)


if app.debug:
    logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=18000,
            debug = True, threaded = True)
