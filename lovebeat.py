import copy
import json
import logging
import sys
import time

from flask import Flask, g, render_template, request, make_response, jsonify
from flask import redirect, url_for
import redis

sys.stdout = sys.stderr
MAX_SAVED = 100
DEFAULT_CONF = {'heartbeat': {'warning': 10, 'error': 20}, 'labels': []}
app = Flask(__name__)
pool = redis.ConnectionPool(host='localhost', port=6379, db=0)


def get_ts():
    if app.config.get('TESTING'):
        return app.config['TESTING_TS']
    return int(time.time())


def use_test_db(port):
    global pool
    pool = redis.ConnectionPool(host='localhost', port=port, db=0)
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


def load_service_config(sid):
    conf = g.db.hget("lb:s:%s" % sid, "conf")
    if not conf:
        return False, copy.deepcopy(DEFAULT_CONF)
    return True, json.loads(conf)


def update_labels(pipe, sid, old_lbls, new_lbls):
    pipe.sadd("lb:services:all", sid)
    # only modify labels if we are setting new ones. They shall be
    # persistent otherwise.
    if len(new_lbls) == 0:
        return
    for lbl in new_lbls - old_lbls:
        pipe.sadd("lb:services:%s" % lbl, sid)
        pipe.sadd("lb:labels", lbl)
    for lbl in old_lbls - new_lbls:
        pipe.srem("lb:services:%s" % lbl, sid)


@app.route("/s/<sid>/unmaint", methods = ["GET", "POST"])
def unmaint(sid):
    conf_present, conf = load_service_config(sid)
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
    conf_present, conf = load_service_config(sid)
    conf['maint'] = {'type': type,
                     'expiry': now + expiry}
    g.db.hset("lb:s:%s" % sid, "conf", json.dumps(conf))


@app.route("/s/<sid>/delete", methods = ["POST"])
def delete(sid):
    conf_present, conf = load_service_config(sid)
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
    conf_present, old_conf = load_service_config(sid)
    new_conf = copy.deepcopy(old_conf)
    new_lbls = set([l.lower() for l in new_lbls])
    old_lbls = set(new_conf.get('labels', []))
    if new_lbls:
        new_conf['labels'] = sorted(new_lbls)
    if ehb is not None or whb is not None:
        if whb is not None and ehb is not None and whb > ehb:
            whb = None
        new_conf['heartbeat']['error'] = ehb
        new_conf['heartbeat']['warning'] = whb
    if new_conf.get('maint', {}).get('type') == 'soft':
        del new_conf['maint']
    with g.db.pipeline() as pipe:
        update_labels(pipe, sid, old_lbls, new_lbls)
        pipe.hset("lb:s:%s" % sid, "last", '%d:1' % now)
        pipe.lpush("lb:s:%s:h" % sid, '%d:1' % now)
        pipe.ltrim("lb:s:%s:h" % sid, 0, MAX_SAVED - 1)
        if not conf_present or new_conf != old_conf:
            pipe.hset("lb:s:%s" % sid, "conf", json.dumps(new_conf))
        pipe.execute()


@app.template_filter('pretty_interval')
def pinterval(i):
    if i == 0:
        return "now"
    s = []
    num_days = int(i / 86400)
    num_minutes = int(i / 60)
    if num_days > 0:
        s.append("%dd" % num_days)
        i = i % 86400
    if num_days < 10 and i >= 3600:
        s.append("%dh" % int(i / 3600))
        i = i % 3600
    if num_days == 0 and i >= 60:
        s.append("%dm" % int(i / 60))
        i = i % 60

    # round the number to "two entries" and skip seconds whereever possible
    if num_minutes < 5 and i > 0:
        s.append("%ds" % i)
    return "".join(s[0:2])


def eval_service(service, now):
    last_heartbeat = now - service.get('last', {}).get('ts', 0)
    conf = service['config']
    hb_warn = conf['heartbeat']['warning']
    hb_err = conf['heartbeat']['error']

    service['status'] = 'ok'
    if hb_warn and last_heartbeat >= hb_warn:
        service['status'] = 'warning'
    if hb_err and last_heartbeat >= hb_err:
        service['status'] = 'error'
    if 'maint' in conf and conf['maint']['expiry'] >= now:
        service['status'] = 'maint'


def get_services(lbl):
    fields = ("#", "lb:s:*->last", "lb:s:*->conf")
    services = []
    for sid, last, conf in \
            chunks(g.db.sort("lb:services:%s" % lbl, by="nosort",
                             get=fields), 3):
        ts, lval = last.split(":")
        service = {'id': sid,
                   'config': json.loads(conf),
                   'last': {'ts': int(ts), 'val': lval}}
        services.append(service)
    services.sort(lambda a, b: cmp(a['id'], b['id']))
    return services


@app.route("/dashboard/<lbl>/", methods = ["GET"])
def get_list(lbl):
    now = get_ts()
    services = get_services(lbl)
    for service in services:
        eval_service(service, now)
        service['last_heartbeat'] = now - service.get('last', {}).get('ts', 0)

    has_warnings = len([s for s in services if s['status'] == 'warning']) > 0
    has_errors = len([s for s in services if s['status'] == 'error']) > 0
    return render_template("dashboardui.html", services=services,
                           has_warnings=has_warnings,
                           has_errors=has_errors,
                           lbl=lbl)


@app.route("/dashboard/", methods = ["GET"])
def list_labels():
    labels = list(g.db.smembers('lb:labels'))
    labels.sort(lambda a, b: cmp(a.upper(), b.upper()))
    return render_template("list_labels.html",
                           labels=labels)


@app.route("/dashboard/<lbl>/raw", methods = ["GET"])
def get_list_raw(lbl):
    now = get_ts()
    services = get_services(lbl)
    for service in services:
        eval_service(service, now)

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
    now = get_ts()
    services = get_services(lbl)
    for service in services:
        eval_service(service, now)
    return jsonify(services=services)


@app.route("/", methods = ["GET"])
def index():
    return redirect(url_for('.get_list', lbl='all'))


if app.debug:
    logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=18000,
            debug = True, threaded = True)
