"""
Access the CKAN API to update datasets and resources.
"""

from collections import ChainMap

from airflow.utils.decorators import apply_defaults
from airflow.hooks.base_hook import BaseHook

from ckanapi import RemoteCKAN

USER_AGENT = "airflow-fastetl/0.1 (+https://github.com/economiagovbr/FastETL)"

class CKANHook(BaseHook):

    @apply_defaults
    def __init__(self,
        conn_id: str,
        *args,
        **kwargs
        ):
        self.conn_id = conn_id
    
    def _get_catalog(self):
        conn = BaseHook.get_connection(self.conn_id)
        ckan_url = f"{conn.schema}://{conn.host}"
        if getattr(conn, "port", None):
            ckan_url += f":{conn.port}"
        if getattr(conn, "password", None):
            return RemoteCKAN(ckan_url, apikey=conn.password,
                        user_agent=USER_AGENT)
        else:
            return RemoteCKAN(ckan_url,
                        user_agent=USER_AGENT)

    def create_or_update_resource(
        self,
        dataset_id: str,
        name: str,
        url: str,
        format_: str,
        description: str = None,
        ):
        "Creates or updates a resource on CKAN."
        catalog = self._get_catalog()
        dataset = catalog.action.package_show(id=dataset_id)
        matching_resources = [
            resource \
            for resource in dataset["resources"] \
            if resource["url"] == url]
        if matching_resources:
            resource = matching_resources[0]
            new_resource = dict(ChainMap(
                {
                    'name': name,
                    'url': url,
                    'description': resource['description'] if description is None else description,
                    'format': format_
                },
                resource
            ))
            catalog.action.resource_update(**new_resource)
        else: # create resource
            catalog.action.resource_create(
                package_id=dataset_id,
                url=url,
                name=name,
                format=format_,
                description=description
            )
