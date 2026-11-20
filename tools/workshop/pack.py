#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Create a reproducible Activiti BAR, including the compiled Preact form."""
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
output = Path(sys.argv[1])
bpmn = root / 'openidm/workflow/servicePrincipalOwner.bpmn20.xml'
model = ET.fromstring(bpmn.read_bytes())
ns = {'b': 'http://www.omg.org/spec/BPMN/20100524/MODEL'}
form_key = model.find('.//b:userTask', ns).attrib['{http://activiti.org/bpmn}formKey']
if form_key != 'forms/servicePrincipalOwner.html':
    raise ValueError('Unexpected review formKey: ' + form_key)
start_key = model.find('.//b:startEvent', ns).attrib['{http://activiti.org/bpmn}formKey']
if start_key != 'forms/servicePrincipalOwnerStart.html':
    raise ValueError('Unexpected start formKey: ' + start_key)
resources = {
    'servicePrincipalOwner.bpmn20.xml': bpmn.read_bytes(),
    start_key: (output / 'servicePrincipalOwnerStart.html').read_bytes(),
    form_key: (output / 'servicePrincipalOwner.html').read_bytes(),
    'licenses/PREACT.txt': (root / 'openidm/workflow-form/node_modules/preact/LICENSE').read_bytes(),
    'licenses/CDDL-1.1.txt': (root / 'LICENSE.md').read_bytes(),
}
archive = output / 'servicePrincipalOwner.bar'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bar:
    for name, content in resources.items():
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        bar.writestr(info, content)
print(f'BAR: {archive} ({archive.stat().st_size} bytes)')
