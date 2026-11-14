"""Deterministic camera fixtures, not reconstruction or live inference evidence."""
import copy
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from test_browser_3d import scene_page

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='opt-in browser checks')


@pytest.fixture
def viewer_server():
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    app = FastAPI()
    app.mount('/static', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'app' / 'static'))

    @app.get('/')
    def index():
        return HTMLResponse('''<!doctype html><html><head><script type="importmap">{"imports":{"three":"/static/vendor/three/three.module.js"}}</script></head>
        <body><p>Deterministic viewer fixture — no live inference.</p><div id="model" style="width:900px;height:600px;position:relative"></div>
        <script type="module">import {BlueprintViewer} from '/static/viewer.js';window.blueprintViewer=new BlueprintViewer(document.querySelector('#model'));</script></body></html>''')

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.started
    yield f'http://127.0.0.1:{sock.getsockname()[1]}'
    server.should_exit = True
    thread.join(5)
    sock.close()


def fixture_scene():
    def element(identifier, kind, center, size, rotation=0):
        return {'id': identifier, 'kind': kind, 'name': identifier, 'storey_id': 'upper',
                'source': {'kind': 'image', 'page': 1, 'bbox': [.2, .3, .6, .7]},
                'properties': [], 'assumptions': [{'property': 'height', 'value': 1.2, 'reason': 'Fixture display height'}],
                'representation': 'reconstructed',
                'geometry': {'type': 'box', 'center': center, 'size': size, 'rotation_z': rotation}}
    window = element('rotated-window', 'window', [2, 1, 3], [2, .12, 1.2], .7853981633974483)
    # A real mesh path as well as the box adapter: rotate a rectangular prism.
    import math
    positions = []
    for z in [2.4, 3.6]:
        for x, y in [(-1, -.06), (1, -.06), (1, .06), (-1, .06)]:
            positions.extend([2 + (x-y)/math.sqrt(2), 1 + (x+y)/math.sqrt(2), z])
    window['geometry'] = {'type': 'mesh', 'positions': positions,
                          'indices': [0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6, 0, 4, 5, 0, 5, 1, 1, 5, 6, 1, 6, 2, 2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0]}
    unresolved = element('unresolved-window', 'window', [0, 0, 0], [1, 1, 1])
    unresolved.update(geometry=None, representation='unresolved', note='Fixture: host unknown')
    return {'document_id': 'fixture', 'building_id': 'fixture', 'revision_id': 'r1', 'revision_number': 1,
            'derived': True, 'units': 'relative', 'floors': [
                {'id': 'lower', 'label': 'Lower', 'source': {'kind': 'image', 'page': 1, 'bbox': [0, 0, 1, 1]}, 'transform': []},
                {'id': 'upper', 'label': 'Upper', 'source': {'kind': 'image', 'page': 1, 'bbox': [0, 0, 1, 1]}, 'transform': []}],
            'elements': [window, element('square-object', 'other', [-2, 1, 3], [1, 1, 1]),
                         element('wall', 'wall', [0, 0, 1.5], [10, .2, 3]), unresolved]}


def load_fixture(page, url):
    page.goto(url)
    page.wait_for_function('window.blueprintViewer')
    scene = fixture_scene()
    page.evaluate('scene=>window.blueprintViewer.loadScene(scene)', scene)
    return scene


def test_camera_framing_rotated_geometry_uncertainty_and_source_preservation(viewer_server, scene_page):
    page = scene_page
    original = load_fixture(page, viewer_server)
    result = page.evaluate('''() => {
      const v=window.blueprintViewer;
      v.setHighlights(['rotated-window','unresolved-window','missing'],true);
      v.setShowAssumptions(true);
      const focus=v.focusObject('rotated-window');
      const before=v.getCameraState();
      const frame=v.frameIds(['rotated-window','unresolved-window','missing'],{topDown:true});
      return {focus,before,frame,after:v.getSnapshot(),data:v.data};
    }''')
    assert result['focus']['orientation'] == 'geometry'
    assert 'viewing choice' in result['focus']['note']
    assert result['frame'] == {'framed_ids': ['rotated-window'], 'unavailable_ids': ['unresolved-window', 'missing']}
    after = result['after']
    assert after['selected_id'] == 'rotated-window'
    assert after['highlight_ids'] == ['rotated-window'] and after['show_assumptions']
    delta = [p-t for p, t in zip(after['camera_position'], after['camera_target'])]
    assert delta[2] > 0 and abs(delta[0]) + abs(delta[1]) < delta[2] * .00001
    assert result['data'] == original
    # The close-up's horizontal direction is normal to the actual rotated axis.
    direction = [p-t for p, t in zip(result['before']['position'], result['before']['target'])]
    assert abs(direction[0] + direction[1]) < .00001
    fallback = page.evaluate("window.blueprintViewer.focusObject('square-object')")
    assert fallback['orientation'] == 'uncertain' and 'Approximate' in fallback['note']
    before = page.evaluate('window.blueprintViewer.getCameraState()')
    unavailable = page.evaluate("window.blueprintViewer.focusObject('unresolved-window')")
    assert unavailable['orientation'] == 'unavailable'
    assert page.evaluate('window.blueprintViewer.getCameraState()') == before


def test_camera_restore_manual_orbit_themes_and_atomic_revision(viewer_server, scene_page):
    page = scene_page
    scene = load_fixture(page, viewer_server)
    page.evaluate("window.blueprintViewer.setExploded(true);window.blueprintViewer.focusObject('rotated-window')")
    saved = page.evaluate('window.blueprintViewer.getCameraState()')
    assert saved['target'][2] > 3
    # Direct browser interaction keeps normal orbit available after programmatic framing.
    canvas = page.locator('#model canvas')
    box = canvas.bounding_box()
    page.mouse.move(box['x'] + 450, box['y'] + 300)
    page.mouse.down()
    page.mouse.move(box['x'] + 540, box['y'] + 350, steps=8)
    page.mouse.up()
    assert page.evaluate('window.blueprintViewer.getCameraState().position') != saved['position']
    assert page.evaluate('s=>window.blueprintViewer.setCameraState(s)', saved)
    page.wait_for_timeout(120)
    restored = page.evaluate('window.blueprintViewer.getCameraState()')
    assert restored['position'] == pytest.approx(saved['position'], abs=1e-8)
    assert restored['target'] == pytest.approx(saved['target'], abs=1e-8)
    assert not page.evaluate('s=>window.blueprintViewer.setCameraState({...s,position:s.target})', saved)
    assert not page.evaluate('s=>window.blueprintViewer.setCameraState({...s,up:[0,0,0]})', saved)
    for theme, color in [('dark', '#121110'), ('light', '#fbfaf8')]:
        result = page.evaluate('theme=>{const v=window.blueprintViewer;v.setTheme(theme);return {color:"#"+v.scene.background.getHexString(),camera:v.getCameraState()}}', theme)
        assert result['color'] == color
        assert result['camera']['position'] == pytest.approx(saved['position'], abs=1e-8)
    page.evaluate("window.blueprintViewer.setHighlights(['rotated-window']);window.blueprintViewer.setShowAssumptions(true);window.blueprintViewer.setHighlightsEnabled(false)")
    replacement = copy.deepcopy(scene)
    replacement.update(revision_id='r2', revision_number=2)
    replacement['elements'] = [e for e in replacement['elements'] if e['id'] != 'square-object']
    page.evaluate('scene=>window.blueprintViewer.loadScene(scene)', replacement)
    result = page.evaluate('window.blueprintViewer.getSnapshot()')
    assert result['selected_id'] == 'rotated-window'
    assert result['show_assumptions'] and not result['highlights_enabled']
    assert result['camera_position'] == pytest.approx(saved['position'], abs=1e-8)
    assert result['highlight_ids'] == ['rotated-window']


def test_native_nonrendered_records_never_receive_mesh_highlights(viewer_server, scene_page):
    page = scene_page
    scene = fixture_scene()
    scene['derived'] = False
    scene['elements'][-1]['representation'] = 'reconstructed'
    page.goto(viewer_server)
    page.wait_for_function('window.blueprintViewer')
    page.evaluate('scene=>window.blueprintViewer.loadScene(scene)', scene)
    result = page.evaluate("() => {const v=window.blueprintViewer;v.setHighlights(['unresolved-window']);return {ids:[...v.highlightIds],focus:v.focusObject('unresolved-window')}}")
    assert result['ids'] == []
    assert result['focus']['orientation'] == 'unavailable'
