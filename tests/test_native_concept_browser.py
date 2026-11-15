"""Real Chromium presentation regressions; fixture geometry, no inference calls."""
import os

import pytest

from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks"
)


def open_viewer(page, origin, scene):
    # Isolate the real viewer modules from unrelated application/session APIs.
    page.route(origin + "/", lambda route: route.fulfill(
        content_type="text/html",
        body='''<!doctype html><script type="importmap">{"imports":{
        "three":"/static/vendor/three/three.module.js"}}</script>
        <div id="model" style="width:900px;height:700px"></div>''',
    ))
    page.goto(origin)
    page.evaluate("""async scene => {
      const {BlueprintViewer}=await import('/static/viewer.js');
      window.viewer=new BlueprintViewer(document.querySelector('#model'));
      viewer.loadScene(scene);
    }""", scene)


def test_native_concept_without_drawing_frames_preserves_exact_meshes(static_server, scene_page):
    scene = {"document_id": "native-fixture", "revision_id": "native-r1",
             "derived": False, "units": "m", "floors": [], "elements": [],
             "comparison": [], "warnings": []}
    # Native storeys have no projection from an original drawing. Cover the
    # actual empty-array payload, absent frame and malformed optional frames.
    for i, frame in enumerate(([], None, [[1, 0], [0, 1]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]])):
        floor = {"id": f"f{i}", "label": f"Native storey {i}",
                 "base_elevation": i * 4, "reference_height": 3}
        if frame is not None:
            floor["transform"] = frame
        if i == 3:
            floor["building_transform"] = []
        scene["floors"].append(floor)
        scene["elements"].append({
            "id": f"native{i}", "name": "Supplied IFC fixture", "kind": "fixture",
            "semantic_type": "cabinet", "storey_id": floor["id"],
            "source": {"kind": "ifc", "global_id": f"native{i}"},
            "properties": [{"name": "Original property", "value": f"value{i}"}],
            "assumptions": [], "geometry_origin": "extracted",
            "geometry": {"type": "mesh", "positions": [
                0, 0, i * 4, 2, 0, i * 4, 0, 1, i * 4, .3, .2, i * 4 + 2],
                "indices": [0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3]},
        })
    page = scene_page
    open_viewer(page, static_server, scene)
    result = page.evaluate("""() => {
      const v=viewer, original=JSON.stringify(v.data);
      const buffers=()=>JSON.stringify([...v.meshes].map(([id,m])=>({id,
        uuid:m.geometry.uuid,positions:Array.from(m.geometry.attributes.position.array),
        indices:Array.from(m.geometry.index.array)})));
      const before=buffers();
      v.setMode('concept');
      const sourceMeshes=[];
      v.concept.group.traverse(m=>{if(m.isMesh&&m.userData.sourceElementId)sourceMeshes.push(m);});
      const exact=sourceMeshes.length===v.meshes.size&&sourceMeshes.every(m=>{
        const source=v.meshes.get(m.userData.sourceElementId);
        return m.geometry===source.geometry&&m.position.equals(source.position)
          &&m.quaternion.equals(source.quaternion)&&m.scale.equals(source.scale);
      });
      const styled=sourceMeshes.every(m=>m.material!==v.meshes.get(m.userData.sourceElementId).material);
      v.setFloorFilter('f1');v.setTheme('dark');v.setCutawayPercent(50);
      const filtered=[...v.concept.floors].map(([id,f])=>[id,f.group.visible]);
      const nativeRecords=[...v.concept.records.values()];
      v.setMode('inspection');v.setTheme('light');v.setMode('concept');
      const state=v.getSnapshot();
      return {exact,styled,filtered,nativeRecords,state,
        emptyFrames:v.concept.sourceRings.size===0,
        dataUnchanged:original===JSON.stringify(v.data),buffersUnchanged:before===buffers()};
    }""")
    assert result["exact"] and result["styled"]
    assert result["emptyFrames"] and result["dataUnchanged"] and result["buffersUnchanged"]
    assert result["filtered"] == [["f0", False], ["f1", True], ["f2", False], ["f3", False]]
    assert all(record["kind"] == "source" for record in result["nativeRecords"])
    assert {record["source_id"] for record in result["nativeRecords"]} == {
        item["id"] for item in scene["elements"]}
    assert result["state"]["mode"] == "concept"
    assert result["state"]["theme"] == "light"
    assert result["state"]["floor_filter"] == "f1"
    assert result["state"]["cutaway_percent"] == 50
    assert result["state"]["concept_build_count"] == 1


def test_derived_concept_composes_valid_frames_and_rejects_invalid_revision(static_server, scene_page):
    scene = {"document_id": "derived-fixture", "revision_id": "r1", "revision_number": 1,
             "derived": True, "units": "m", "warnings": [],
             "floors": [{"id": "f1", "label": "Drawing floor", "base_elevation": 0,
                         "reference_height": 3, "transform": [[2, 0, 0], [0, 2, 0], [0, 0, 1]],
                         "building_transform": [[1, 0, 10], [0, 1, 20], [0, 0, 1]]}],
             "comparison": [{"floor_id": "f1", "element_id": "cabinet", "polygons": [
                 [[1, 0], [2, 0], [2, .5], [1, .5], [1, 0]]]}],
             "elements": [{"id": "cabinet", "name": "Source cabinet", "kind": "furniture",
                           "semantic_type": "cabinet", "storey_id": "f1", "assumptions": [],
                           "geometry": {"type": "box", "size": [2, 1, 1], "center": [13, 20.5, .5]}}]}
    page = scene_page
    open_viewer(page, static_server, scene)
    result = page.evaluate("""() => {
      const v=viewer, before=JSON.stringify(v.data);v.setMode('concept');
      const record=v.concept.records.get('cabinet');
      let styledMeshes=0;v.concept.group.traverse(m=>{if(m.isMesh&&m.userData.conceptRecord==='cabinet')styledMeshes++;});
      const source=v.meshes.get('cabinet');let disposed=false;
      source.geometry.addEventListener('dispose',()=>disposed=true);
      const invalid=structuredClone(v.data);invalid.revision_id='r2';invalid.revision_number=2;
      invalid.floors[0].transform=[[]];
      let error='';try{v.prepareRevision(invalid);}catch(e){error=e.message;}
      return {ring:v.concept.sourceRings.get('cabinet'),record,styledMeshes,error,
        retained:!disposed&&v.meshes.get('cabinet')===source&&JSON.stringify(v.data)===before};
    }""")
    assert result["ring"] == [[[12, 20], [14, 20], [14, 21], [12, 21], [12, 20]]]
    assert result["record"]["kind"] == "source" and not result["record"]["fallback"]
    assert result["styledMeshes"] > 1
    assert result["error"] == "Invalid drawing source-comparison frame"
    assert result["retained"]
