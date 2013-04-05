import logging
import time

from flask import Flask, g, render_template, request, make_response, jsonify
from flask import redirect, url_for
import redis

MAX_SAVED = 100
DEFAULT_COND = "e:heartbeat:20;w:heartbeat:10"
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


@app.route("/s/<sid>", methods = ["GET", "POST"])
def update(sid):
    now = int(time.time())
    old_lbls, old_maint = g.db.hmget("lb:s:%s" % sid, "lbls", "maint")
    old_lbls = old_lbls or ""
    old_lbls = set([l for l in old_lbls.split(",") if l])
    new_lbls = set([])
    if request.form.get('labels'):
        new_lbls = [l.strip() for l in request.form['labels'].split(',')]
        new_lbls = set([l for l in new_lbls if l])
    conds = []
    for key, value in request.form.items(multi=True):
        if key == 'error':
            conds.append('e:%s' % value)
        elif key == 'warning':
            conds.append('w:%s' % value)
    cond = ';'.join(conds)
    new_maint = request.form.get('maint')
    with g.db.pipeline() as pipe:
        pipe.sadd("lb:services:all", sid)
        # Remove 'soft maintentance' if we get a good status
        for lbl in new_lbls - old_lbls:
            pipe.sadd("lb:services:%s" % lbl, sid)
            pipe.sadd("lb:labels", lbl)
        for lbl in old_lbls - new_lbls:
            pipe.srem("lb:services:%s" % lbl, sid)
        if old_lbls != new_lbls:
            pipe.hset("lb:s:%s" % sid, "lbls", ",".join(sorted(new_lbls)))

        if new_maint:
            maint_type, expiry = new_maint.split(":")
            expiry = int(expiry) + now
            pipe.hset("lb:s:%s" % sid, "maint", "%s:%d" % (maint_type, expiry))
        else:
            if old_maint:
                maint_type, expiry = old_maint.split(":")
                if maint_type == 'soft':
                    pipe.hset("lb:s:%s" % sid, "maint", "")
            pipe.lpush("lb:s:%s:h" % sid, '%d:1' % now)
            pipe.ltrim("lb:s:%s:h" % sid, 0, MAX_SAVED - 1)
            pipe.hset("lb:s:%s" % sid, "lval", '1')
            pipe.hset("lb:s:%s" % sid, "ts", now)
            if conds:
                pipe.hset("lb:s:%s" % sid, "cond", cond)
        pipe.execute()
    return "ok"


def parse_conds(cond):
    conds = []
    for c in [c for c in cond.split(";") if c]:
        t, key, expr = c.split(":")
        conds.append((t, key, expr))
    return conds


def eval_conds(conds, lval, ts, now):
    errors = []
    warnings = []
    for t, key, expr in conds:
        l = errors if t == 'e' else warnings
        if key == 'heartbeat':
            limit = int(expr)
            if (now - ts) > limit:
                m = "Heartbeat last seen %d seconds ago, limit = %d seconds"
                l.append(m % (now - ts, limit))
    return warnings, errors


def get_services(lbl):
    now = int(time.time())
    fields = ("#", "lb:s:*->lval", "lb:s:*->ts", "lb:s:*->cond", "lb:s:*->maint")
    services = []
    for sid, lval, ts, cond, maint in \
            chunks(g.db.sort("lb:services:%s" % lbl, get=fields), 5):
        conds = parse_conds(cond or DEFAULT_COND)
        warnings, errors = eval_conds(conds, lval, int(ts), now)
        status = 'ok'
        if maint:
            maint_type, maint_expiry = maint.split(":")
            if int(maint_expiry) >= now:
                status = 'maint'
        if status != 'maint' and len(errors) > 0:
            status = 'error'
        elif status != 'maint' and len(warnings) > 0:
            status = 'warning'
        services.append({'sid': sid, 'ts': ts, 'status': status,
                         'warnings': warnings, 'errors': errors})
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
