lovebeat
========

Super simple heartbeat and metrics monitoring, created and maintained by [Victor Boivie](http://twitter.com/vboivie).

Installation
============

First of all, you will need to have [redis](http://redis.io) running.

To install the dependencies, it is recommended to use virtualenv:

    $ virtualenv ENV
    $ . ENV/bin/activate
    $ pip install -r requirements.txt

To start it as a development server, just run:

    $ python app.py

Usage
=====
Reporting heartbeats
--------------------

To report a heartbeat, simply call curl http://localhost:18000/s/HEARTBEAT_ID, where HEARTBEAT_ID is a name of your choice. If it doesn't exist, it will be created.

Example:

    curl http://localhost:18000/s/`hostname`

Then visit <http://localhost:18000/dashboard/all/> to see it.

Specifying timeouts
-------------------

    curl http://localhost:18000/s/HEARTBEAT_ID -d error=heartbeat:30 -d warning=heartbeat:6

The values are in seconds. The defaults are to issue warnings after 10 seconds and errors after 20 seconds. The settings will be remembered, so you only need to specify them once, but it will not do harm if you specify them all the time.

Specifying labels
-----------------

This makes is possible to group heartbeats and use <http://localhost:18000/dashboard/LABEL_NAME/> as the url   to the dashboard. Just comma-separate them.

    curl http://localhost:18000/s/HEARTBEAT_ID -d labels=LABEL1,LABEL2

Schedules Maintenance
---------------------

By setting a heartbeat in 'maintenance mode', you can pause it to avoid generating warnings and errors. The maintentance mode is always limited by an expiry so that you will not forget about it. There are two options: soft and hard mode. The soft maintenance mode will automatically be disabled once the heartbeat are generated again. The hard maintenance mode will continue until it is expired.

    curl http://localhost:18000/s/HEARTBEAT_ID-d maint=hard:3600

    curl http://localhost:18000/s/HEARTBEAT_ID-d maint=soft:300

Connecting to external services
-------------------------------

It is very simple to have external monitoring systems such as [Pingdom](http://www.pingdom.com), [Zabbix](http://www.zabbix.com/) or similar poll the dashboard to see the status of the services. However, HTML is not the best representation in those cases. So look at these endpoints instead:

- http://localhost:18000/dashboard/all/raw
- http://localhost:18000/dashboard/all/json

Copyright and License
=====================

    Copyright 2013 Victor Boivie

    Licensed under the Apache License, Version 2.0 (the
    "License"); you may not use this work except in
    compliance with the License. You may obtain a copy of 
    the License in the LICENSE file, or at:

    http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in
    writing, software distributed under the License is
    distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
    OR CONDITIONS OF ANY KIND, either express or implied. 
    See the License for the specific language governing
    permissions and limitations under the License.
