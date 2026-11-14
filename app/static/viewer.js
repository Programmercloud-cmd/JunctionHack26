import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';

const COLORS = {wall:0xd2d9ce,room:0x7daa8c,outdoor:0xa5c58e,railing:0x91a6a5,open_edge:0x73a886,door:0xb58b64,window:0x78b4bf,stairs:0xc0a981,furniture:0xc7b6cc,fixture:0x9abac6,other:0xabb5ab};

export class BlueprintViewer {
  constructor(container, {onSelect = () => {}, onUnresolvedSelect = () => {}} = {}) {
    this.container = container;
    this.onSelect = onSelect;
    this.onUnresolvedSelect = onUnresolvedSelect;
    this.annotations = [];
    this.elements = new Map();
    this.meshes = new Map();
    this.highlightIds = new Set();
    this.highlightsEnabled = true;
    this.showAssumptions = false;
    this.selectedId = null;
    this.floorFilter = '';
    this.exploded = false;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xeef1e9);
    this.camera = new THREE.PerspectiveCamera(42, 1, .01, 10000);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(6,-8,6);
    this.renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.domElement.setAttribute('aria-label', 'Interactive building model. Drag to orbit, scroll to zoom, right-drag to pan. Select objects using the element list below.');
    this.renderer.domElement.tabIndex = 0;
    this.renderer.domElement.dataset.ready = 'false';
    container.append(this.renderer.domElement);
    this.annotationLayer = document.createElement('div');
    this.annotationLayer.className = 'model-annotations';
    this.annotationLayer.setAttribute('aria-label', 'Unresolved source annotations, not model geometry');
    container.append(this.annotationLayer);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = .08;
    this.controls.addEventListener('change', () => this.render());
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.8));
    const sunlight = new THREE.DirectionalLight(0xffffff, 3);
    sunlight.position.set(30, -20, 50);
    this.scene.add(sunlight);
    const fill = new THREE.DirectionalLight(0xd9e9ff, 1.2);
    fill.position.set(-30, 25, 10);
    this.scene.add(fill);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.raycaster = new THREE.Raycaster();
    this.pointerDown = null;
    this.renderer.domElement.addEventListener('pointerdown', (event) => { this.pointerDown = [event.clientX, event.clientY]; });
    this.renderer.domElement.addEventListener('pointerup', (event) => this.pick(event));
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.renderer.setAnimationLoop(() => { this.controls.update(); this.render(); });
    this.resize();
  }

  loadScene(data) {
    this.clearGeometry();
    this.data = data;
    this.elements = new Map(data.elements.map((element) => [element.id, element]));
    this.selectedId = null;
    this.floorFilter = '';
    this.exploded = false;
    this.floorIndices = new Map((data.floors || []).map((floor, index) => [floor.id, index]));
    this.highlightIds.clear();
    for (const element of data.elements) {
      if (!element.geometry) continue;
      const input = element.geometry;
      let geometry;
      if (input.type === 'mesh') {
        geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(input.positions, 3));
        geometry.setIndex(input.indices);
        geometry.computeVertexNormals();
      } else if (input.type === 'box') {
        geometry = new THREE.BoxGeometry(...input.size);
      } else if (input.type === 'floor') {
        const shape = new THREE.Shape();
        input.polygon.forEach(([x,y], i) => i ? shape.lineTo(x,y) : shape.moveTo(x,y));
        shape.closePath();
        geometry = new THREE.ShapeGeometry(shape);
      } else continue;
      const material = new THREE.MeshStandardMaterial({color:COLORS[element.kind] || COLORS.other, roughness:.82, metalness:0, side:THREE.DoubleSide});
      const mesh = new THREE.Mesh(geometry, material);
      mesh.userData.elementId = element.id;
      if (input.type === 'box') { mesh.position.set(...input.center); mesh.rotation.z = input.rotation_z || 0; }
      if (input.type === 'floor') mesh.position.z = input.elevation || 0;
      mesh.userData.baseZ = mesh.position.z;
      if (data.derived) {
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), new THREE.LineBasicMaterial({color:0x53685b, transparent:true, opacity:.38}));
        mesh.add(edges);
      }
      this.meshes.set(element.id, mesh);
      this.group.add(mesh);
    }
    this.bounds = new THREE.Box3().setFromObject(this.group);
    const size = this.bounds.getSize(new THREE.Vector3());
    this.floorSeparation = Math.max(size.z * 1.2, Math.max(size.x,size.y) * .16, .1);
    this.createAnnotations();
    this.applyAppearance();
    this.fit();
    this.renderer.domElement.dataset.ready = 'true';
    this.renderer.domElement.dataset.documentId = data.document_id;
    this.renderer.domElement.dataset.meshCount = String(this.meshes.size);
  }

  setHighlights(ids, enabled = true) {
    this.highlightIds = new Set((ids || []).filter((id) => this.elements.has(id) && this.elements.get(id).representation !== 'unresolved' && (!this.data?.derived || this.meshes.has(id))));
    this.highlightsEnabled = enabled;
    this.applyAppearance();
  }

  setShowAssumptions(enabled) { this.showAssumptions = enabled; this.applyAppearance(); }

  setFloorFilter(id) {
    this.floorFilter = this.floorIndices.has(id) ? id : '';
    this.applyAppearance();
    this.updateBounds();
    this.fit();
  }

  setExploded(enabled) {
    this.exploded = enabled;
    for (const [id, mesh] of this.meshes) {
      const index = this.floorIndices.get(this.elements.get(id).storey_id) || 0;
      mesh.position.z = mesh.userData.baseZ + (enabled ? index * this.floorSeparation : 0);
    }
    this.group.updateMatrixWorld(true);
    this.updateBounds();
    this.fit();
    this.renderer.domElement.dataset.exploded = String(enabled);
  }

  updateBounds() {
    this.bounds = new THREE.Box3();
    for (const mesh of this.meshes.values()) if (mesh.visible) this.bounds.union(new THREE.Box3().setFromObject(mesh));
  }

  createAnnotations() {
    if (!this.data.derived) return;
    const floors = new Map((this.data.floors || []).map((floor) => [floor.id,floor]));
    const floorTops = new Map();
    for (const [id,mesh] of this.meshes) {
      const floorId=this.elements.get(id).storey_id;
      floorTops.set(floorId,Math.max(floorTops.get(floorId) || 0,new THREE.Box3().setFromObject(mesh).max.z));
    }
    const coarse = new Map();
    const append = (floor, elements, bbox, floorLevel) => {
      const matrix = floor.transform;
      if (!Array.isArray(matrix) || matrix.length !== 3 || matrix.some((row) => !Array.isArray(row) || row.length !== 3 || !row.every(Number.isFinite))) return;
      const u=(bbox[0]+bbox[2])/2, v=(bbox[1]+bbox[3])/2;
      const z=floorTops.get(floor.id) || 0;
      const anchor=new THREE.Vector3(matrix[0][0]*u+matrix[0][1]*v+matrix[0][2],matrix[1][0]*u+matrix[1][1]*v+matrix[1][2],z+.08);
      const button=document.createElement('button');
      button.type='button';
      button.className=`unresolved-annotation${floorLevel ? ' floor-annotation' : ''}`;
      button.textContent=floorLevel ? `? ${elements.length} unresolved · ${floor.label}` : '?';
      button.dataset.annotationKind=floorLevel ? 'floor' : 'source-region';
      button.dataset.elementIds=JSON.stringify(elements.map((element)=>element.id));
      const label=floorLevel ? `${elements.length} unresolved items on ${floor.label}; locations are not established. Inspect original source.` : `${elements[0].name}: unresolved source region, not model geometry. Approximate annotation position. Inspect original source.`;
      button.title=label;
      button.setAttribute('aria-label',label);
      button.addEventListener('click',()=>this.onUnresolvedSelect({floor,elements,floorLevel}));
      this.annotationLayer.append(button);
      this.annotations.push({button,floorId:floor.id,elementIds:elements.map((element)=>element.id),floorLevel,anchor});
    };
    for (const element of this.elements.values()) {
      if (element.representation !== 'unresolved' && element.geometry) continue;
      const floor=floors.get(element.storey_id), box=element.source.bbox;
      if (!floor || element.source.kind !== 'image' || !Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite)) continue;
      const floorLevel=/unlocalized|coarse floor/i.test(element.note || '') || box.every((value,index)=>Math.abs(value-floor.source.bbox[index])<1e-6);
      if (floorLevel) {
        if (!coarse.has(floor.id)) coarse.set(floor.id,[]);
        coarse.get(floor.id).push(element);
      } else append(floor,[element],box,false);
    }
    for (const [floorId,elements] of coarse) { const floor=floors.get(floorId); append(floor,elements,floor.source.bbox,true); }
  }

  positionAnnotations() {
    const width=this.container.clientWidth, height=this.container.clientHeight;
    const occupied=[];
    for (const item of this.annotations) {
      const anchor=item.anchor.clone();
      if (this.exploded) anchor.z+=(this.floorIndices.get(item.floorId) || 0)*this.floorSeparation;
      anchor.project(this.camera);
      item.button.hidden=Boolean((this.floorFilter && this.floorFilter!==item.floorId) || anchor.z < -1 || anchor.z > 1 || Math.abs(anchor.x)>1 || Math.abs(anchor.y)>1);
      if (item.button.hidden) continue;
      const halfWidth=Math.min(width/2,item.button.offsetWidth/2 || 14);
      const x=Math.max(halfWidth,Math.min(width-halfWidth,(anchor.x+1)*width/2));
      let y=Math.max(16,Math.min(height-16,(1-anchor.y)*height/2));
      // Annotations may overlap in the drawing. Stack only their screen labels;
      // source coordinates and all model geometry remain untouched.
      while (occupied.some((other)=>Math.abs(other.x-x)<halfWidth+other.halfWidth+4 && Math.abs(other.y-y)<30) && y+30<height-16) y+=30;
      occupied.push({x,y,halfWidth});
      item.button.style.left=`${x}px`;
      item.button.style.top=`${y}px`;
    }
  }

  select(id) {
    if (!this.elements.has(id)) return;
    const floor = this.elements.get(id).storey_id;
    if (this.floorFilter && this.floorFilter !== floor) this.setFloorFilter(this.floorIndices.has(floor) ? floor : '');
    this.selectedId = id;
    this.applyAppearance();
    this.onSelect(this.elements.get(id));
  }

  applyAppearance() {
    const active = this.highlightsEnabled && this.highlightIds.size > 0;
    for (const [id, mesh] of this.meshes) {
      const element = this.elements.get(id);
      const highlight = active && this.highlightIds.has(id);
      const selected = id === this.selectedId;
      // Native IFC spaces are often enclosed volumes; keep them out of the way
      // until requested. Inferred room floors remain visible as footprints.
      mesh.visible = (!this.floorFilter || element.storey_id === this.floorFilter) && (this.data.derived || element.kind !== 'room' || element.geometry.type === 'floor' || highlight || selected);
      const assumed = this.showAssumptions && element.assumptions.length > 0;
      const roomColors = [0xa8c2a5,0xabc6c9,0xd9c7a6,0xbeb7ce,0xd1baad];
      const roomColorIndex = [...(element.name || id)].reduce((sum, character) => sum + character.charCodeAt(0), 0) % roomColors.length;
      const baseColor = this.data.derived && element.kind === 'room' ? roomColors[roomColorIndex] : COLORS[element.kind] || COLORS.other;
      mesh.material.color.setHex(highlight ? 0xcce979 : assumed ? 0xe4ae55 : baseColor);
      const opacity = active && !highlight ? .1 : !this.data.derived && element.kind === 'room' && element.geometry.type === 'mesh' ? .58 : element.kind === 'window' ? .65 : 1;
      mesh.material.opacity = opacity;
      mesh.material.transparent = opacity < 1;
      mesh.material.depthWrite = opacity >= 1;
      mesh.material.emissive.setHex(selected ? 0x264a24 : highlight ? 0x17250a : 0);
      mesh.material.emissiveIntensity = .35;
      mesh.material.needsUpdate = true;
      for (const edge of mesh.children) edge.material.opacity = active && !highlight ? .04 : .38;
    }
    this.renderer.domElement.dataset.highlightIds = JSON.stringify([...this.highlightIds]);
    this.renderer.domElement.dataset.highlightsEnabled = String(this.highlightsEnabled);
    this.renderer.domElement.dataset.showAssumptions = String(this.showAssumptions);
    this.renderer.domElement.dataset.selectedId = this.selectedId || '';
    this.renderer.domElement.dataset.floorFilter = this.floorFilter;
    this.render();
  }

  fit() {
    if (!this.bounds || this.bounds.isEmpty()) return;
    const center = this.bounds.getCenter(new THREE.Vector3());
    const size = this.bounds.getSize(new THREE.Vector3());
    const extent = Math.max(size.x,size.y,size.z, .1);
    const direction = new THREE.Vector3(.9,-1.2,this.data?.derived ? 1.65 : .9).normalize();
    const viewRotation = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().lookAt(direction, new THREE.Vector3(), this.camera.up)).invert();
    const tanVertical = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const tanHorizontal = tanVertical * this.camera.aspect;
    let distance = extent * .1;
    // Fit every bounds corner in camera space, including the narrower screen
    // dimension. Source geometry is untouched; only the viewpoint changes.
    for (const x of [this.bounds.min.x,this.bounds.max.x]) {
      for (const y of [this.bounds.min.y,this.bounds.max.y]) {
        for (const z of [this.bounds.min.z,this.bounds.max.z]) {
          const corner = new THREE.Vector3(x,y,z).sub(center).applyQuaternion(viewRotation);
          distance = Math.max(distance, corner.z + Math.abs(corner.x)/tanHorizontal, corner.z + Math.abs(corner.y)/tanVertical);
        }
      }
    }
    distance *= 1.12;
    this.camera.near = Math.max(extent / 10000, .001);
    this.camera.far = Math.max(extent * 100, 100);
    this.camera.position.copy(center).add(direction.multiplyScalar(distance));
    this.controls.target.copy(center);
    this.controls.minDistance = extent * .04;
    this.controls.maxDistance = extent * 20;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.render();
  }

  pick(event) {
    if (!this.pointerDown || Math.hypot(event.clientX-this.pointerDown[0], event.clientY-this.pointerDown[1]) > 5 || event.button !== 0) return;
    this.pointerDown = null;
    const bounds = this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2((event.clientX-bounds.left)/bounds.width*2-1, -(event.clientY-bounds.top)/bounds.height*2+1), this.camera);
    const active = this.highlightsEnabled && this.highlightIds.size > 0;
    const meshes = [...this.meshes.values()].filter((mesh) => mesh.visible && (!active || this.highlightIds.has(mesh.userData.elementId)));
    const hit = this.raycaster.intersectObjects(meshes, false)[0];
    if (hit) this.select(hit.object.userData.elementId);
  }

  resize() {
    const width = this.container.clientWidth, height = this.container.clientHeight;
    if (!width || !height) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width,height);
    this.render();
  }
  render() { if (this.renderer && this.container.clientWidth) { this.renderer.render(this.scene,this.camera); this.positionAnnotations(); } }
  getSnapshot() {
    return {document_id:this.data?.document_id, mesh_count:this.meshes.size, element_count:this.elements.size, selected_id:this.selectedId, highlight_ids:[...this.highlightIds], highlights_enabled:this.highlightsEnabled, show_assumptions:this.showAssumptions, floor_filter:this.floorFilter, exploded:this.exploded, camera_position:this.camera.position.toArray(), up_axis:this.camera.up.toArray(), annotations:this.annotations.map((item)=>({element_ids:item.elementIds,floor_id:item.floorId,floor_level:item.floorLevel,visible:!item.button.hidden})), elements:[...this.meshes].map(([id,mesh])=>({id,visible:mesh.visible,opacity:mesh.material.opacity,display_offset_z:mesh.position.z-mesh.userData.baseZ}))};
  }
  clearGeometry() {
    for (const mesh of this.meshes.values()) { mesh.geometry.dispose(); mesh.material.dispose(); for (const edge of mesh.children) { edge.geometry.dispose(); edge.material.dispose(); } }
    this.meshes.clear();
    this.group.clear();
    this.annotations=[];
    this.annotationLayer.replaceChildren();
  }
  dispose() { this.renderer.setAnimationLoop(null); this.resizeObserver.disconnect(); this.controls.dispose(); this.clearGeometry(); this.renderer.dispose(); this.renderer.domElement.remove(); this.annotationLayer.remove(); }
}
