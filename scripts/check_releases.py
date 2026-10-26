# -*- coding: utf-8 -*-
import json, urllib.request

releases = json.loads(urllib.request.urlopen('https://api.github.com/repos/Eynzof/Hermes-CN-Core/releases?per_page=30', timeout=30).read())
for r in releases:
    tag = r['tag_name']
    for asset in r.get('assets', []):
        if 'json' in asset['name'] or 'manifest' in asset['name'].lower():
            try:
                m = json.loads(urllib.request.urlopen(asset['browser_download_url'], timeout=15).read())
                print(f"{tag}: runtimeVersion={m.get('runtimeVersion')}, kernelVersion={m.get('kernelVersion')}")
            except (FileNotFoundError, IOError, KeyError, PermissionError, json.JSONDecodeError) as e:
                pass
