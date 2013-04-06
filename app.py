import json
import logging
import time

from flask import Flask, g, render_template, request, make_response, jsonify
from flask import redirect, url_for
import redis

MAX_SAVED = 100
DEFAULT_CONF = {'wheartbeat': 10, 'eheartbeat': 20}
app = Flask(__name__)
pool = redis.ConnectionPool(host='localhost', port=6379, db=0)


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
        return DEFAULT_CONF
    return json.loads(conf)


def handle_conds(items, conf):
    if 'heartbeat' in dict(items):
        if 'eheartbeat' in conf:
            del conf['eheartbeat']
        if 'wheartbeat' in conf:
            del conf['wheartbeat']
    for key, value in items:
        if key == 'heartbeat':
            if ':' in value:
                type, value = value.split(":")
            else:
                type, value = 'error', value
            if type == 'error':
                conf['eheartbeat'] = int(value)
            elif type == 'warning':
                conf['wheartbeat'] = int(value)


def handle_maint(maint, now, conf):
    if 'maint' in conf and conf['maint']['type'] != 'hard':
        del conf['maint']
    if maint:
        type, expiry = maint.split(':')
        conf['maint'] = {'type': type,
                         'expiry': now + int(expiry)}


def format_lbls(req):
    if req:
        new_lbls = [l.strip() for l in req.split(',')]
        return set([l for l in new_lbls if l])
    return set([])


def format_maint(req):
    return req


def update_labels(pipe, sid, old_lbls, new_lbls):
    pipe.sadd("lb:services:all", sid)
    for lbl in new_lbls - old_lbls:
        pipe.sadd("lb:services:%s" % lbl, sid)
        pipe.sadd("lb:labels", lbl)
    for lbl in old_lbls - new_lbls:
        pipe.srem("lb:services:%s" % lbl, sid)


@app.route("/s/<sid>", methods = ["GET", "POST"])
def update(sid):
    now = int(time.time())
    conf = get_old_conf(sid)
    new_lbls = format_lbls(request.form.get('labels'))
    old_lbls = set(conf.get('labels', []))
    if new_lbls:
        conf['labels'] = sorted(new_lbls)
    handle_conds(request.form.items(multi=True), conf)
    handle_maint(request.form.get('maint'), now, conf)

    with g.db.pipeline() as pipe:
        update_labels(pipe, sid, old_lbls, new_lbls)
        pipe.hset("lb:s:%s" % sid, "last", '%d:1' % now)
        pipe.lpush("lb:s:%s:h" % sid, '%d:1' % now)
        pipe.ltrim("lb:s:%s:h" % sid, 0, MAX_SAVED - 1)
        if conf:
            pipe.hset("lb:s:%s" % sid, "conf", json.dumps(conf))
        pipe.execute()
    return "ok"


@app.template_filter('pretty_interval_simple')
def ago(i):
    s = ""
    if i >= 86400:
        s += "%dd" % int(i / 3600)
        i = i % 86400
    if i >= 3600:
        s += "%dh" % int(i / 3600)
        i = i % 3600
    if i >= 60:
        s += "%dm" % int(i / 60)
        i = i % 60
    if s == "" and i > 0:
        s += "%ds" % i
    return s


@app.template_filter('pretty_interval')
def ago(i):
    s = ""
    if i >= 86400:
        s += "%dd" % int(i / 3600)
        i = i % 86400
    if i >= 3600:
        s += "%dh" % int(i / 3600)
        i = i % 3600
    if i >= 60:
        s += "%dm" % int(i / 60)
        i = i % 60
    if i > 0:
        s += "%ds" % i
    return s


def eval_service(conf, service, now):
    if 'wheartbeat' in conf and service['last_heartbeat'] > conf['wheartbeat']:
        service['wheartbeat'] = True
        service['status'] = 'warning'
    if 'eheartbeat' in conf and service['last_heartbeat'] > conf['eheartbeat']:
        service['eheartbeat'] = True
        service['status'] = 'error'


def get_services(lbl):
    now = int(time.time())
    fields = ("#", "lb:s:*->last", "lb:s:*->conf")
    services = []
    for sid, last, conf in \
            chunks(g.db.sort("lb:services:%s" % lbl, get=fields), 3):
        ts, lval = last.split(":")
        ts = int(ts)
        conf = json.loads(conf) if conf else DEFAULT_CONF
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
