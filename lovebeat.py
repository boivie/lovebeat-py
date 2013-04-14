import copy
import json
import logging
import sys
import time

from flask import Flask, g, render_template, request, make_response, jsonify
from flask import redirect, url_for, Response, stream_with_context
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


def rvtrans(db, func, *watches, **kwargs):
    shard_hint = kwargs.pop('shard_hint', None)
    rv = None
    with g.db.pipeline(True, shard_hint) as pipe:
        while 1:
            try:
                if watches:
                    pipe.watch(*watches)
                rv = func(pipe)
                pipe.execute()
                return rv
            except redis.WatchError:
                continue


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


def load_service_config(pipe, sid):
    conf = pipe.hget("lb:s:%s" % sid, "conf")
    if not conf:
        return False, copy.deepcopy(DEFAULT_CONF)
    return True, json.loads(conf)


def load_service_state(pipe, sid):
    state = pipe.hget("lb:s:%s" % sid, "state")
    if not state:
        alert = {'status': 'ok', 'id': 0, 'state': 'confirmed'}
        return {'last': {}, 'status': 'ok', 'alert': alert}
    return json.loads(state)


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


@app.route("/l/<lbl>", methods = ["POST"])
def update_label(lbl):
    alert_warning = set()
    alert_error = set()
    if request.form:
        for key, value in request.form.items(multi=True):
            if key == 'alert':
                type, rest = value.split(":", 1)
                if type == 'warning':
                    alert_warning.add(rest)
                elif type == 'error':
                    alert_error.add(rest)

    with g.db.pipeline() as pipe:
        pipe.multi()
        pipe.sadd('lb:labels', lbl)
        config = {'alerts': {'error': list(alert_error),
                             'warning': list(alert_warning)}}
        pipe.hset('lb:l:%s' % lbl, 'config', json.dumps(config))
        pipe.execute()
    return "ok"


@app.route("/l/<lbl>", methods = ["GET"])
def get_label(lbl):
    config = g.db.hget('lb:l:%s' % lbl, 'config')
    if not config:
        return jsonify()
    return jsonify(**json.loads(config))


@app.route("/s/<sid>/unmaint", methods = ["GET", "POST"])
def unmaint(sid):
    def trans(pipe):
        state = load_service_state(pipe, sid)
        if 'maint' in state:
            del state['maint']
        # don't calculate 'status' here, let that be done in 'eval'
        pipe.multi()
        pipe.hset("lb:s:%s" % sid, "state", json.dumps(state))

    g.db.transaction(trans, 'lb:s:%s' % sid)
    if request.json:
        return jsonify()
    return "ok\n"


@app.route("/s/<sid>/maint", methods = ["GET", "POST"])
def maint(sid):
    now = get_ts()
    type = "soft"
    expiry = 10 * 60

    def trans(pipe):
        state = load_service_state(pipe, sid)
        state['maint'] = {'type': type, 'expiry': now + expiry}
        state['status'] = 'maint'
        pipe.multi()
        pipe.hset("lb:s:%s" % sid, "state", json.dumps(state))

    if request.json:
        type = request.json.get('type', type)
        expiry = int(request.json.get('expiry'), expiry)
        g.db.transaction(trans, 'lb:s:%s' % sid)
        return jsonify()
    elif request.form:
        type = request.form.get('type', type)
        expiry = int(request.form.get('expiry', expiry))
    g.db.transaction(trans, 'lb:s:%s' % sid)
    return "ok\n"


@app.route("/s/<sid>/delete", methods = ["POST"])
def delete(sid):
    def trans(pipe):
        conf_present, conf = load_service_config(pipe, sid)
        lbls = set(conf.get('labels', []))
        lbls.add('all')
        pipe.multi()
        for lbl in lbls:
            pipe.srem("lb:services:%s" % lbl, sid)
        pipe.delete("lb:s:%s" % sid)
        pipe.delete("lb:s:%s:h" % sid)

    g.db.transaction(trans, 'lb:s:%s' % sid)

    if request.json:
        return jsonify()
    return "ok\n"


@app.route("/s/<sid>", methods = ["GET", "POST"])
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
    new_lbls = set([l.lower() for l in new_lbls])
    if whb is not None and ehb is not None and whb > ehb:
        whb = None

    def trans(pipe):
        conf_present, old_conf = load_service_config(pipe, sid)
        new_conf = copy.deepcopy(old_conf)
        state = load_service_state(pipe, sid)
        old_lbls = set(new_conf.get('labels', []))
        if new_lbls:
            new_conf['labels'] = sorted(new_lbls)
        if ehb is not None or whb is not None:
            new_conf['heartbeat']['error'] = ehb
            new_conf['heartbeat']['warning'] = whb
        if state.get('maint', {}).get('type') == 'soft':
            del state['maint']
        pipe.multi()
        update_labels(pipe, sid, old_lbls, new_lbls)
        state['last']['ts'] = now
        state['last']['val'] = 1
        pipe.hset("lb:s:%s" % sid, "state", json.dumps(state))
        pipe.lpush("lb:s:%s:h" % sid, '%d:1' % now)
        pipe.ltrim("lb:s:%s:h" % sid, 0, MAX_SAVED - 1)
        if not conf_present or new_conf != old_conf:
            pipe.hset("lb:s:%s" % sid, "conf", json.dumps(new_conf))

    g.db.transaction(trans, 'lb:s:%s' % sid)


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


def eval_status(conf, state, now):
    last_heartbeat = now - state['last'].get('ts', 0)
    hb_warn = conf['heartbeat']['warning']
    hb_err = conf['heartbeat']['error']

    new_status = 'ok'
    if hb_warn and last_heartbeat >= hb_warn:
        new_status = 'warning'
    if hb_err and last_heartbeat >= hb_err:
        new_status = 'error'
    if 'maint' in state and \
            state['maint']['expiry'] >= now:
        new_status = 'maint'
    return new_status


def update_alert(service, now):
    state = service['state']
    alert_status = state['alert']['status']
    status = 'ok' if state['status'] == 'maint' else state['status']
    # can we do a status transition?
    if alert_status != status and state['alert']['state'] == 'confirmed':
        def trans(pipe):
            state['alert'] = {'id': state['alert']['id'],
                              'status': status,
                              'state': 'new',
                              'ts': get_ts()}
            if alert_status == 'ok':
                state['alert']['id'] += 1

            pipe.multi()
            pipe.hset('lb:s:%s' % service['id'], 'state', json.dumps(state))
        g.db.transaction(trans, 'lb:s:%s' % service['id'])


def update_status(service, now):
    old_status = service['state']['status']
    new_status = eval_status(service['config'], service['state'], now)
    if new_status != old_status:
        def trans(pipe):
            state = load_service_state(pipe, service['id'])
            state['status'] = eval_status(service['config'], state, now)
            service['state'] = state

            pipe.multi()
            pipe.hset('lb:s:%s' % service['id'], 'state', json.dumps(state))
        g.db.transaction(trans, 'lb:s:%s' % service['id'])


def eval_service(service, now):
    update_status(service, now)
    update_alert(service, now)

    last_heartbeat = now - service['state']['last'].get('ts', 0)
    service['state']['last']['delta'] = last_heartbeat


def get_services(lbl):
    fields = ("#", "lb:s:*->state", "lb:s:*->conf")
    services = []
    for sid, state, conf in \
            chunks(g.db.sort("lb:services:%s" % lbl, by="nosort",
                             get=fields), 3):
        service = {'id': sid,
                   'config': json.loads(conf),
                   'state': json.loads(state)}
        services.append(service)
    return services


@app.route("/dashboard/<lbl>/", methods = ["GET"])
def get_list(lbl):
    now = get_ts()
    services = get_services(lbl)
    for service in services:
        eval_service(service, now)

    has_warnings = len([s for s in services if s['state']['status'] == 'warning']) > 0
    has_errors = len([s for s in services if s['state']['status'] == 'error']) > 0
    services.sort(lambda a, b: cmp(a['id'], b['id']))

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

    has_warnings = len([s for s in services if s['state']['status'] == 'warning']) > 0
    has_errors = len([s for s in services if s['state']['status'] == 'error']) > 0
    has_maint = len([s for s in services if s['state']['status'] == 'maint']) > 0
    services.sort(lambda a, b: cmp(a['id'], b['id']))
    html = render_template("dashboard.html", services=services,
                           has_warnings=has_warnings,
                           has_errors=has_errors,
                           has_maint=has_maint)
    resp = make_response(html)
    resp.headers["Content-type"] = "text/plain"
    return resp


@app.route("/dashboard/<lbl>/status", methods = ["GET"])
def show_short(lbl):
    now = get_ts()
    services = get_services(lbl)
    for service in services:
        eval_service(service, now)

    has_warnings = len([s for s in services if s['state']['status'] == 'warning']) > 0
    has_errors = len([s for s in services if s['state']['status'] == 'error']) > 0
    has_maint = len([s for s in services if s['state']['status'] == 'maint']) > 0

    if has_errors:
        s = "down+error"
    elif has_warnings:
        s = "down+warning"
    elif has_maint:
        s = "up+maint"
    else:
        s = "up+flawless"

    resp = make_response(s)
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


def get_labels():
    fields = ("#", "lb:l:*->config")
    labels = {}
    for lbl, config in \
            chunks(g.db.sort("lb:labels", by="nosort", get=fields), 2):
        if config:
            labels[lbl] = json.loads(config)
    return labels


def plain(t):
    return Response(t, mimetype='text/plain')


@app.route("/agent/<agent>/claim/<service>/<int:alert_id>/<status>",
           methods = ["POST"])
def claim(agent, service, alert_id, status):
    def trans(pipe):
        state = load_service_state(pipe, service)
        # claiming an old alert - a race condition.
        if state['alert']['id'] != alert_id:
            return plain("already_claimed")
        if state['alert']['status'] != status:
            return plain("already_claimed")
        # Already claimed?
        if 'claim' in state['alert']:
            if state['alert']['claim']['agent'] == agent:
                return plain("ok")
            else:
                return plain("already_claimed")
        if state['alert']['state'] != 'new':
            return plain('already_claimed')
        pipe.multi()
        state['alert']['state'] = 'claimed'
        state['alert']['claim'] = {'agent': agent}
        pipe.hset('lb:s:%s' % service, 'state', json.dumps(state))
        return plain("ok")
    return rvtrans(g.db, trans, 'lb:s:%s' % service)


@app.route("/agent/<agent>/confirm/<service>/<int:alert_id>/<status>",
           methods = ["POST"])
def confirm(agent, service, alert_id, status):
    def trans(pipe):
        state = load_service_state(pipe, service)
        # confirming an old alert - a race condition.
        if state['alert']['state'] in ('new', 'claimed') and \
                state['alert']['id'] == alert_id and \
                state['alert']['status'] == status:
            pass
        else:
            return plain('already_confirmed')
        pipe.multi()
        state['alert']['state'] = 'confirmed'
        state['alert']['confirmed'] = {'agent': agent}
        pipe.hset('lb:s:%s' % service, 'state', json.dumps(state))
        return plain("ok")
    return rvtrans(g.db, trans, 'lb:s:%s' % service)


@app.route("/agent/<agent>/alerts.txt", methods = ["GET"])
def alerts_txt(agent):
    now = get_ts()
    services = get_services("all")
    label_configs = get_labels()

    def generate():
        def gather_rcpt(labels, status):
            rcpt = set()
            for lbl in labels + ["all"]:
                config = label_configs.get(lbl)
                if config:
                    rcpt.update(set(config['alerts'][status]))
            return list(rcpt)

        # API version
        yield '1\n'

        for service in services:
            eval_service(service, now)
            if service['state']['status'] in ('warning', 'error'):
                status = service['state']['status']
                rcpt = gather_rcpt(service['config']['labels'], status)
                if not rcpt:
                    continue
                sid = service['id']
                alert_id = service['state']['alert']['id']
                yield "SERVICE\n%s\n" % sid
                yield "ALERTID\n%s\n" % alert_id
                yield "TYPE\n%s\n" % status
                yield "TO\n%s\n" % (" ".join(rcpt),)
                yield "SUBJECT\nDOWN alert: %s is DOWN [#%d]\n" % (sid, alert_id)
                yield "MESSAGE\n"
                yield "%s is down with %s status.\n" % (sid, status)
                yield "\nYours Sincerely\nLovebeat\nEOF\n"
                yield "ENDSERVICE\n"

        yield "ENDFILE\n"
    return Response(stream_with_context(generate()), mimetype='text/plain')


if app.debug:
    logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=18000,
            debug = True, threaded = True)
