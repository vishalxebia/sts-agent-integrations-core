# (C) Datadog, Inc. 2010-2016
# All rights reserved
# Licensed under Simplified BSD License (see LICENSE)

# stdlib

# 3rd party
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.packages.urllib3 import disable_warnings

# Disable https warnings
disable_warnings(InsecureRequestWarning)

# project
from checks import AgentCheck, CheckException

EVENT_TYPE = SOURCE_TYPE_NAME = 'servicenow'


class ServicenowCheck(AgentCheck):

    INSTANCE_TYPE = "servicenow_cmdb"
    SERVICE_CHECK_NAME = "servicenow.cmdb.topology_information"
    service_check_needed = True
    service_check_done = False

    auth = None  # http basic authentication
    timeout = None  # connection timeout
    instance_key = None  # unique key to identify this check from its instances.
    # The same check might be run on multiple clusters
    base_url = None  # base url of where CMDB instance can be found, for example: https://dev12406.service-now.com
    relation_types = {}  # relation types that are available in table cmdb_rel_type
    instance_tags = []

    def check(self, instance):
        if 'url' not in instance:
            raise Exception('ServiceNow CMDB topology instance missing "url" value.')
        if 'basic_auth' not in instance:
            raise Exception('ServiceNow CMDB topology instance missing "basic_auth" value.')

        basic_auth = instance['basic_auth']
        if 'user' not in basic_auth:
            raise Exception('ServiceNow CMDB topology instance missing "basic_auth.user" value.')
        if 'password' not in basic_auth:
            raise Exception('ServiceNow CMDB topology instance missing "basic_auth.password" value.')

        self.relation_types = {}

        basic_auth_user = basic_auth['user']
        basic_auth_password = basic_auth['password']
        self.auth = (basic_auth_user, basic_auth_password)

        self.base_url = instance['url']

        self.instance_key = {
            "type": self.INSTANCE_TYPE,
            "url": self.base_url
        }

        self.instance_tags = instance.get('tags', [])

        default_timeout = self.init_config.get('default_timeout', 5)
        self.timeout = float(instance.get('timeout', default_timeout))

        self._process_and_cache_relation_types()
        self.start_snapshot(self.instance_key)
        self._process_components()
        self._process_component_relations()
        self.stop_snapshot(self.instance_key)

    def _collect_components(self):
        """
        collect components from ServiceNow CMDB's cmdb_ci table
        :return: dict, raw response from CMDB
        """
        url = self.base_url + '/api/now/table/cmdb_ci?sysparm_fields=name,sys_id,sys_class_name,sys_created_on'

        return self._get_json(url, self.timeout, self.auth)

    def _process_components(self):
        """
        process components fetched from CMDB
        :return: nothing
        """
        state = self._collect_components()

        for component in state['result']:
            id = component['sys_id']
            type = {
                "name": component['sys_class_name']
            }
            data = {
                "name": component['name'].strip(),
                "tags": self.instance_tags
            }

            self.component(self.instance_key, id, type, data)

    def _collect_relation_types(self):
        """
        collects relations from CMDB
        :return: dict, raw response from CMDB
        """
        url = self.base_url + '/api/now/table/cmdb_rel_type?sysparm_fields=sys_id,parent_descriptor'

        return self._get_json(url, self.timeout, self.auth)

    def _process_and_cache_relation_types(self):
        """
        collect available relations from cmdb_rel_ci and cache them in self.relation_types dict.
        :return: nothing
        """
        state = self._collect_relation_types()

        for relation in state['result']:
            id = relation['sys_id']
            parent_descriptor = relation['parent_descriptor']
            self.relation_types[id] = parent_descriptor

    def _collect_component_relations(self, offset, batch_size):
        """
        collect relations between components from cmdb_rel_ci and publish these in batches.
        """
        url = self.base_url + '/api/now/table/cmdb_rel_ci?sysparm_fields=parent,type,child'

        return self._get_json_batch(url, offset, batch_size)

    def _process_component_relations(self):
        BATCH_SIZE = 100
        offset = 0

        completed = False
        while not completed:
            state = self._collect_component_relations(offset, BATCH_SIZE)['result']

            for relation in state:

                parent_sys_id = relation['parent']['value']
                child_sys_id = relation['child']['value']
                type_sys_id = relation['type']['value']

                relation_type = {
                    "name": self.relation_types[type_sys_id]
                }
                data = {
                    "tags": self.instance_tags
                }

                self.relation(self.instance_key, parent_sys_id, child_sys_id, relation_type, data)

            completed = len(state) < BATCH_SIZE
            offset += BATCH_SIZE

    def _get_json_batch(self, url, offset, batch_size):
        limit_args = "&sysparm_query=ORDERBYsys_created_on&sysparm_offset=%i&sysparm_limit=%i" % (offset, batch_size)
        limited_url = url + limit_args
        return self._get_json(limited_url, self.timeout, self.auth)

    def _get_json(self, url, timeout, auth=None, verify=True):
        tags = ["url:%s" % url]
        msg = None
        status = None
        resp = None
        try:
            resp = requests.get(url, timeout=timeout, auth=auth, verify=verify)
            if resp.status_code != 200:
                status = AgentCheck.CRITICAL
                msg = "Got %s when hitting %s" % (resp.status_code, url)
            else:
                status = AgentCheck.OK
                msg = "ServiceNow CMDB instance detected at %s " % url
        except requests.exceptions.Timeout as e:
            # If there's a timeout
            msg = "%s seconds timeout when hitting %s" % (timeout, url)
            status = AgentCheck.CRITICAL
        except Exception as e:
            msg = str(e)
            status = AgentCheck.CRITICAL
        finally:
            if not self.service_check_done or status is AgentCheck.CRITICAL:
                self.make_service_check(status, tags=tags, msg=msg)

        if resp.encoding is None:
            resp.encoding = 'UTF8'

        return resp.json()

    def make_service_check(self, status, tags, msg):
        self.service_check_done = True
        if self.service_check_needed and status is AgentCheck.OK:
            self.service_check(self.SERVICE_CHECK_NAME, status, tags=tags,
                               message=msg)
            self.service_check_needed = False
        if status is AgentCheck.CRITICAL:
            self.service_check(self.SERVICE_CHECK_NAME, status, tags=tags,
                               message=msg)
            raise CheckException("Cannot connect to ServiceNow CMDB, please check your configuration.")