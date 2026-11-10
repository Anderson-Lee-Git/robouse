"""Preserve attached-child resource directories used by the frozen RoboCasa stack.

MuJoCo 4 no longer supplies the parent's resource directories to attached MJCF.
Only resource references in private in-memory copies change; disk assets do not.
Unsupported includes in a child fail explicitly rather than guessing their scope.
"""

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path


def resolve(xml):
    root = ET.fromstring(xml)
    models = root.findall('./asset/model[@file]')
    if not models:
        return xml, {}
    compiler = root.find('compiler')
    inherited = dict(compiler.attrib) if compiler is not None else {}
    assets = {}
    visiting = set()

    def child(path, parent_options):
        path = Path(path).resolve()
        if path in visiting:
            raise ValueError('cycle in attached MJCF resources')
        visiting.add(path)
        r = ET.fromstring(path.read_bytes())
        if r.findall('.//include'):
            raise ValueError('attached MJCF includes require a separate resource-scope audit')
        c = r.find('compiler')
        local = dict(c.attrib) if c is not None else {}
        opts = dict(parent_options)
        if 'assetdir' in local:
            opts.update(meshdir=local['assetdir'], texturedir=local['assetdir'])
        opts.update(local)
        identities = []
        for n in r.findall('./asset/*[@file]'):
            f = Path(n.get('file'))
            if n.tag == 'model':
                key = child(path.parent / f, opts)
                n.set('file', key)
                identities.append((n, key))
            else:
                directory = opts.get('assetdir', '')
                if n.tag == 'mesh':
                    directory = opts.get('meshdir', directory)
                if n.tag == 'texture':
                    directory = opts.get('texturedir', directory)
                if opts.get('strippath') == 'true':
                    f = Path(f.name)
                full = (path.parent / directory / f).resolve()
                content = full.read_bytes()
                n.set('file', str(full))
                identities.append((n, 'sha256:' + hashlib.sha256(content).hexdigest()))
        data = ET.tostring(r)
        # Virtual names depend on resource bytes, never their machine paths.
        for node, identity in identities:
            node.set('file', identity)
        key = 'robouse-mj4-' + hashlib.sha256(ET.tostring(r)).hexdigest() + '.xml'
        assets[key] = data
        visiting.remove(path)
        return key

    for node in models:
        node.set('file', child(Path(node.get('file')), inherited))
    return ET.tostring(root, encoding='unicode'), assets


def install():
    """Install once in the isolated worker, only for the selected 4.0 engine."""
    import mujoco
    from robosuite.utils.binding_utils import MjSim

    if mujoco.mj_versionString() != '4.0.0' or getattr(MjSim, '_robouse_mj4_resources', False):
        return

    def from_xml_string(xml):
        source, assets = resolve(xml)
        return MjSim(mujoco.MjModel.from_xml_string(source, assets=assets))

    MjSim.from_xml_string = staticmethod(from_xml_string)
    MjSim._robouse_mj4_resources = True
