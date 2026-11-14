import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { ConceptLayer } from './concept.js';

const COLORS = {wall:0xd2d9ce,room:0x7daa8c,outdoor:0xa5c58e,railing:0x91a6a5,open_edge:0x73a886,door:0xb58b64,window:0x78b4bf,stairs:0xc0a981,furniture:0xc7b6cc,fixture:0x9abac6,other:0xabb5ab};

export class BlueprintViewer {
  constructor(container, {onSelect = () => {}, onUnresolvedSelect = () => {}, onProposalSelect = () => {}} = {}) {
    this.container = container;
    this.onSelect = onSelect;
    this.onUnresolvedSelect = onUnresolvedSelect;
    this.onProposalSelect = onProposalSelect;
    this.mode = 'inspection'; this.modeStates = {}; this.cutaway = false; this.cutawayPercent = 100;
    this.conceptBuildCount = 0; this.needsRender = true; this.renderCount = 0;
    this.annotations = [];
    this.elements = new Map();
    this.meshes = new Map();
    this.highlightIds = new Set();
    this.highlightsEnabled = true;
    this.showAssumptions = false;
    this.theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    this.selectedId = null;
    this.floorFilter = '';
    this.exploded = false;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.theme === 'dark' ? 0x121110 : 0xfbfaf8);
    this.camera = new THREE.PerspectiveCamera(42, 1, .01, 10000);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(6,-8,6);
    this.renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.localClippingEnabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.shadowMap.autoUpdate = false;
    this.renderer.domElement.setAttribute('aria-label', 'Interactive building model. Drag to orbit, scroll to zoom, right-drag to pan. Ask in chat to select or inspect objects.');
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
    this.inspectionLights = new THREE.Group(); this.scene.add(this.inspectionLights);
    this.inspectionLights.add(new THREE.AmbientLight(0xffffff, 1.8));
    const sunlight = new THREE.DirectionalLight(0xffffff, 3);
    sunlight.position.set(30, -20, 50);
    this.inspectionLights.add(sunlight);
    const fill = new THREE.DirectionalLight(0xd9e9ff, 1.2);
    fill.position.set(-30, 25, 10);
    this.inspectionLights.add(fill);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.raycaster = new THREE.Raycaster();
    this.pointerDown = null;
    this.renderer.domElement.addEventListener('pointerdown', (event) => { this.pointerDown = [event.clientX, event.clientY]; });
    this.renderer.domElement.addEventListener('pointerup', (event) => this.pick(event));
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.renderer.setAnimationLoop(() => { this.controls.update(); if (this.needsRender && this.container.clientWidth && this.container.clientHeight) { this.renderer.render(this.scene,this.camera); this.positionAnnotations(); this.needsRender=false; this.renderCount++; } });
    this.resize();
  }

  loadScene(data) {
    const candidate=this.prepareRevision(data);
    return this.commitRevision(candidate);
  }

  prepareRevision(data) {
    const building=scene=>scene?.building_id || scene?.document_id;
    if(this.data && building(data)!==building(this.data))throw new Error('Revision belongs to another building');
    if(this.data?.revision_id && data.revision_id===this.data.revision_id)return {noop:true,baseData:this.data,data};
    if(Number.isFinite(this.data?.revision_number)&&Number.isFinite(data.revision_number)&&data.revision_number<=this.data.revision_number)throw new Error('Stale building revision');
    if(new Set(data.elements.map(e=>e.id)).size!==data.elements.length)throw new Error('Duplicate replacement object IDs');
    const candidate={baseData:this.data,data,group:new THREE.Group(),meshes:new Map(),elements:new Map(data.elements.map(e=>[e.id,e])),concept:null};
    try {
    for (const element of data.elements) {
      if (!element.geometry) continue;
      const input = element.geometry;
      let geometry;
      if (input.type === 'mesh') {
        if (!Array.isArray(input.positions) || input.positions.some(v=>!Number.isFinite(v)) || input.positions.length%3 || !Array.isArray(input.indices) || input.indices.some(i=>!Number.isInteger(i)||i<0||i>=input.positions.length/3)) throw new Error('Invalid replacement mesh');
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
      candidate.meshes.set(element.id, mesh);
      candidate.group.add(mesh);
    }

      candidate.bounds=new THREE.Box3().setFromObject(candidate.group);
      const size=candidate.bounds.getSize(new THREE.Vector3());
      candidate.floorSeparation=this.data?this.floorSeparation:Math.max(size.z*1.2,Math.max(size.x,size.y)*.16,.1);
      candidate.floorIndices=new Map();
      for(const floor of data.floors || [])if(this.floorIndices?.has(floor.id))candidate.floorIndices.set(floor.id,this.floorIndices.get(floor.id));
      let index=Math.max(-1,...candidate.floorIndices.values())+1;
      for(const floor of data.floors || [])if(!candidate.floorIndices.has(floor.id))candidate.floorIndices.set(floor.id,index++);
      if(this.concept || this.mode==='concept')candidate.concept=new ConceptLayer(data,candidate.meshes,this.concept?.placements || {});
      candidate.concept?.setCutawayPercent(this.cutawayPercent);
      return candidate;
    } catch(error) {this.disposeRevision(candidate);throw error;}
  }

  disposeRevision(revision) {
    revision.concept?.dispose();
    for(const mesh of revision.meshes?.values() || []){mesh.geometry.dispose();mesh.material.dispose();for(const edge of mesh.children){edge.geometry.dispose();edge.material.dispose();}}
    revision.group?.clear();revision.disposed=true;
  }

  commitRevision(candidate) {
    if(candidate.disposed)throw new Error('Replacement has been disposed');
    if(candidate.baseData!==this.data){if(!candidate.noop)this.disposeRevision(candidate);throw new Error('Stale prepared revision');}
    if(candidate.noop)return this.getSnapshot();
    const initial=!this.data,old={group:this.group,meshes:this.meshes,concept:this.concept};
    const previousSelected=this.selectedId,previousHighlights=[...this.highlightIds];
    this.scene.remove(old.group);if(old.concept)this.scene.remove(old.concept.group);
    this.data=candidate.data;this.group=candidate.group;this.meshes=candidate.meshes;this.elements=candidate.elements;
    this.concept=candidate.concept;this.bounds=candidate.bounds;this.floorIndices=candidate.floorIndices;this.floorSeparation=candidate.floorSeparation;
    this.scene.add(this.group);if(this.concept){this.scene.add(this.concept.group);this.conceptBuildCount++;}
    if(this.floorFilter&&!this.floorIndices.has(this.floorFilter))this.floorFilter='';
    for(const saved of Object.values(this.modeStates))if(saved.floorFilter&&!this.floorIndices.has(saved.floorFilter))saved.floorFilter='';
    this.selectedId=this.elements.has(previousSelected)?previousSelected:null;
    if(this.selectedProposalId&&!this.concept?.records.has(this.selectedProposalId))this.selectedProposalId=null;
    this.highlightIds=new Set(previousHighlights.filter(id=>this.elements.has(id)&&this.elements.get(id).representation!=='unresolved'&&this.meshes.has(id)));
    this.revisionChanges={removed_selection:previousSelected&&!this.selectedId?previousSelected:null,unresolved_selection:this.selectedId&&!this.meshes.has(this.selectedId)?this.selectedId:null,removed_highlights:previousHighlights.filter(id=>!this.highlightIds.has(id))};
    this.annotations=[];this.annotationLayer.replaceChildren();this.createAnnotations();
    this.syncMode();this.syncOffsets();this.applyAppearance();this.updateBounds();
    if(initial)this.fit();
    this.renderer.domElement.dataset.ready='true';this.renderer.domElement.dataset.documentId=this.data.document_id;this.renderer.domElement.dataset.meshCount=String(this.meshes.size);
    this.disposeRevision(old);candidate.committed=true;
    return this.getSnapshot();
  }

  captureView() {
    return {floorFilter:this.floorFilter,exploded:this.exploded,position:this.camera.position.clone(),target:this.controls.target.clone(),up:this.camera.up.clone(),near:this.camera.near,far:this.camera.far,minDistance:this.controls.minDistance,maxDistance:this.controls.maxDistance};
  }
  syncMode() {
    const concept=this.mode==='concept';this.group.visible=!concept;this.inspectionLights.visible=!concept;
    if(this.concept)this.concept.group.visible=concept;
    this.renderer.shadowMap.enabled=concept;this.renderer.shadowMap.needsUpdate=true;
    this.renderer.toneMapping=concept?THREE.ACESFilmicToneMapping:THREE.NoToneMapping;this.renderer.toneMappingExposure=concept?1.12:1;
    this.setTheme(this.theme);this.renderer.domElement.dataset.mode=this.mode;
  }
  setMode(mode) {
    if(!['inspection','concept'].includes(mode)||!this.data||mode===this.mode)return this.getSnapshot();
    const damping=this.controls.enableDamping;this.controls.enableDamping=false;this.controls.update();this.controls.enableDamping=damping;
    this.modeStates[this.mode]=this.captureView();
    if(mode==='concept'&&!this.concept){this.concept=new ConceptLayer(this.data,this.meshes);this.concept.setCutawayPercent(this.cutawayPercent);this.scene.add(this.concept.group);this.conceptBuildCount++;}
    this.mode=mode;const saved=this.modeStates[mode];
    this.floorFilter=saved?.floorFilter ?? this.floorFilter;
    this.exploded=saved?.exploded ?? this.exploded;
    this.syncMode();this.syncOffsets();this.applyAppearance();this.updateBounds();
    if(saved)this.setCameraState({position:saved.position.toArray(),target:saved.target.toArray(),up:(saved.up||this.camera.up).toArray(),near:saved.near,far:saved.far,min_distance:saved.minDistance,max_distance:saved.maxDistance});
    this.render();return this.getSnapshot();
  }
  setCutaway(enabled) {this.setCutawayPercent(enabled?38:100);}
  setCutawayPercent(percent) {
    if(!Number.isFinite(percent))return;
    this.cutawayPercent=Math.max(0,Math.min(100,percent));this.cutaway=this.cutawayPercent<100;
    this.updateClipping();this.renderer.shadowMap.needsUpdate=true;this.render();
  }
  clippingReference(floorId) {
    const floor=(this.data?.floors||[]).find(f=>f.id===floorId);
    if(Number.isFinite(floor?.base_elevation)&&Number.isFinite(floor?.reference_height)&&floor.reference_height>0)return {base:floor.base_elevation,height:floor.reference_height,basis:floor.reference_height_basis};
    const explicit=!floorId?this.data?.uncontained_reference:null;
    if(Number.isFinite(explicit?.base_elevation)&&Number.isFinite(explicit?.reference_height)&&explicit.reference_height>0)return {base:explicit.base_elevation,height:explicit.reference_height,basis:explicit.basis};
    const bounds=new THREE.Box3();
    for(const [id,mesh]of this.meshes)if((this.elements.get(id).storey_id||'')===(floorId||'')){
      const box=new THREE.Box3().setFromObject(mesh);box.translate(new THREE.Vector3(0,0,-(mesh.position.z-mesh.userData.baseZ)));bounds.union(box);
    }
    return bounds.isEmpty()?null:{base:bounds.min.z,height:bounds.max.z-bounds.min.z,basis:'Geometry extent display reference; not measured storey height'};
  }
  updateClipping() {
    const references=new Map();
    for(const [id,mesh] of this.meshes){
      const floorId=this.elements.get(id).storey_id||'';
      if(!references.has(floorId))references.set(floorId,this.clippingReference(floorId));
      const reference=references.get(floorId);
      const offset=this.exploded?(this.floorIndices.get(floorId)||0)*this.floorSeparation:0;
      const planes=this.cutawayPercent<100&&reference?[new THREE.Plane(new THREE.Vector3(0,0,-1),reference.base+reference.height*this.cutawayPercent/100+offset)]:[];
      for(const object of [mesh,...mesh.children])if(object.material){object.material.clippingPlanes=planes;object.material.clipShadows=true;object.material.needsUpdate=true;}
    }
    this.concept?.setCutawayPercent(this.cutawayPercent);
    this.renderer.domElement.dataset.cutawayPercent=String(this.cutawayPercent);
  }
  syncOffsets() {
    for(const [id,mesh]of this.meshes){const index=this.floorIndices.get(this.elements.get(id).storey_id)||0;mesh.position.z=mesh.userData.baseZ+(this.exploded?index*this.floorSeparation:0);}
    this.group.updateMatrixWorld(true);this.concept?.syncVisibility(this.floorFilter,this.exploded,this.floorSeparation,this.floorIndices);
    this.updateClipping();this.renderer.shadowMap.needsUpdate=true;this.renderer.domElement.dataset.exploded=String(this.exploded);
  }

  setHighlights(ids, enabled = true) {
    this.highlightIds = new Set((ids || []).filter((id) => this.elements.has(id) && this.elements.get(id).representation !== 'unresolved' && this.meshes.has(id)));
    this.highlightsEnabled = enabled;
    this.applyAppearance();
  }

  setHighlightsEnabled(enabled) { this.highlightsEnabled = Boolean(enabled); this.applyAppearance(); }

  setTheme(theme) {
    if (!['light','dark'].includes(theme)) return;
    this.theme = theme;
    // Exact Chronicle background tokens; semantic mesh colours remain separate.
    this.scene.background.setHex(theme === 'dark' ? 0x121110 : 0xfbfaf8);
    this.renderer.domElement.dataset.theme = theme;
    this.render();
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
    this.syncOffsets();
    this.updateBounds();
    this.fit();
    this.renderer.domElement.dataset.exploded = String(enabled);
  }

  updateBounds() {
    if(this.mode==='concept'&&this.concept){this.bounds=this.concept.syncVisibility(this.floorFilter,this.exploded,this.floorSeparation,this.floorIndices);this.renderer.shadowMap.needsUpdate=true;return;}
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
      const localX=matrix[0][0]*u+matrix[0][1]*v+matrix[0][2],localY=matrix[1][0]*u+matrix[1][1]*v+matrix[1][2];
      const placement=floor.building_transform||[[1,0,0],[0,1,0],[0,0,1]];
      const anchor=new THREE.Vector3(placement[0][0]*localX+placement[0][1]*localY+placement[0][2],placement[1][0]*localX+placement[1][1]*localY+placement[1][2],z+.08);
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
    this.selectedProposalId=null;
    this.selectedId = id;
    this.applyAppearance();
    this.onSelect(this.elements.get(id));
  }

  applyAppearance() {
    this.concept?.syncVisibility(this.floorFilter,this.exploded,this.floorSeparation,this.floorIndices);
    this.concept?.applyAppearance(this.highlightIds,this.highlightsEnabled,this.selectedProposalId||this.selectedId,this.showAssumptions);
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

  getCameraState() {
    return {position:this.camera.position.toArray(),target:this.controls.target.toArray(),up:this.camera.up.toArray(),near:this.camera.near,far:this.camera.far,min_distance:this.controls.minDistance,max_distance:Number.isFinite(this.controls.maxDistance)?this.controls.maxDistance:this.camera.far};
  }

  setCameraState(saved) {
    const vector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
    if (!saved || !vector(saved.position) || !vector(saved.target) || !vector(saved.up) || saved.up.some((n,i)=>Math.abs(n-[0,0,1][i])>1e-8)) return false;
    const position=new THREE.Vector3(...saved.position),target=new THREE.Vector3(...saved.target);
    if (position.distanceToSquared(target)<1e-16) return false;
    const near=saved.near ?? this.camera.near,far=saved.far ?? this.camera.far;
    const minimum=saved.min_distance ?? this.controls.minDistance,maximum=saved.max_distance ?? this.camera.far;
    if (![near,far,minimum,maximum].every(Number.isFinite) || near<=0 || far<=near || minimum<0 || maximum<=minimum) return false;
    // Flush pending orbit deltas before installing the captured camera. Otherwise
    // a tour interruption can continue drifting after source navigation returns.
    const damping=this.controls.enableDamping;this.controls.enableDamping=false;this.controls.update();this.controls.enableDamping=damping;
    this.camera.position.copy(position);this.controls.target.copy(target);this.camera.up.fromArray(saved.up);
    this.camera.near=near;this.camera.far=far;this.controls.minDistance=minimum;this.controls.maxDistance=maximum;
    this.camera.updateProjectionMatrix();this.controls.update();this.render();
    return true;
  }

  boundsForIds(ids) {
    this.group.updateMatrixWorld(true);
    const bounds=new THREE.Box3(),framed_ids=[],unavailable_ids=[];
    for(const id of new Set(ids || [])) {
      const mesh=this.meshes.get(id),element=this.elements.get(id);
      if(!mesh || !element || element.representation==='unresolved') {unavailable_ids.push(id);continue;}
      const box=new THREE.Box3().setFromObject(mesh);
      if(box.isEmpty()){unavailable_ids.push(id);continue;}
      bounds.union(box);framed_ids.push(id);
    }
    return {bounds,framed_ids,unavailable_ids};
  }

  frameIds(ids, {topDown=false} = {}) {
    const selection=this.boundsForIds(ids);
    const direction=topDown?new THREE.Vector3(0,-1e-6,1):this.camera.position.clone().sub(this.controls.target);
    this.frameBounds(selection.bounds,direction);
    return {framed_ids:selection.framed_ids,unavailable_ids:selection.unavailable_ids};
  }

  focusObject(id) {
    const selection=this.boundsForIds([id]);
    if(!selection.framed_ids.length)return {focused_id:null,orientation:'unavailable',note:'This saved object has no renderable geometry. Inspect its original evidence.'};
    this.select(id);
    const mesh=this.meshes.get(id),positions=mesh.geometry.getAttribute('position');
    const center=selection.bounds.getCenter(new THREE.Vector3());
    // Infer only a viewing axis from the actual rendered vertices. This does not
    // infer a host wall, an exterior side, or any source fact about the object.
    let xx=0,xy=0,yy=0,meanX=0,meanY=0;
    const point=new THREE.Vector3();
    for(let i=0;i<positions.count;i++){point.fromBufferAttribute(positions,i).applyMatrix4(mesh.matrixWorld);meanX+=point.x;meanY+=point.y;}
    meanX/=positions.count;meanY/=positions.count;
    for(let i=0;i<positions.count;i++){point.fromBufferAttribute(positions,i).applyMatrix4(mesh.matrixWorld);const x=point.x-meanX,y=point.y-meanY;xx+=x*x;xy+=x*y;yy+=y*y;}
    const spread=Math.hypot(xx-yy,2*xy),major=(xx+yy+spread)/2,minor=Math.max(0,(xx+yy-spread)/2);
    const reliable=major>1e-12 && minor/major<.16;
    let direction=new THREE.Vector3(.9,-1.2,.8),orientation='uncertain';
    let note='Approximate oblique close-up: this geometry does not establish a clear facing axis.';
    if(reliable){
      const angle=.5*Math.atan2(2*xy,xx-yy);
      direction.set(-Math.sin(angle),Math.cos(angle),0);
      if(direction.dot(this.camera.position.clone().sub(center))<0)direction.negate();
      direction.z=.22;orientation='geometry';
      note='Close-up aligned to modeled geometry; the facing side is a viewing choice, not an established exterior side.';
    }
    this.frameBounds(selection.bounds,direction);
    this.lastFocus={focused_id:id,orientation,note};
    return {...this.lastFocus};
  }

  frameBounds(bounds,direction) {
    if (!bounds || bounds.isEmpty()) return false;
    const damping=this.controls.enableDamping;this.controls.enableDamping=false;this.controls.update();this.controls.enableDamping=damping;
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const extent = Math.max(size.x,size.y,size.z, .1);
    direction=direction.clone();if(direction.lengthSq()<1e-16)direction.set(.9,-1.2,1.65);direction.normalize();
    const viewRotation = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().lookAt(direction, new THREE.Vector3(), this.camera.up)).invert();
    const tanVertical = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const tanHorizontal = tanVertical * this.camera.aspect;
    let distance = extent * .1;
    // Fit every bounds corner in camera space, including the narrower screen
    // dimension. Source geometry is untouched; only the viewpoint changes.
    for (const x of [bounds.min.x,bounds.max.x]) {
      for (const y of [bounds.min.y,bounds.max.y]) {
        for (const z of [bounds.min.z,bounds.max.z]) {
          const corner = new THREE.Vector3(x,y,z).sub(center).applyQuaternion(viewRotation);
          distance = Math.max(distance, corner.z + Math.abs(corner.x)/tanHorizontal, corner.z + Math.abs(corner.y)/tanVertical);
        }
      }
    }
    distance *= 1.12;
    this.camera.near = Math.max(extent / 10000, .001);
    const sceneExtent=this.bounds&&!this.bounds.isEmpty()?this.bounds.getSize(new THREE.Vector3()).length():extent;
    this.camera.far = Math.max(sceneExtent * 100, 100);
    this.camera.position.copy(center).add(direction.multiplyScalar(distance));
    this.controls.target.copy(center);
    this.controls.minDistance = extent * .04;
    this.controls.maxDistance = Math.max(extent,sceneExtent) * 20;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.render();
    return true;
  }

  fit() {
    const direction=this.mode==='concept'?new THREE.Vector3(.35,-.9,1.35):new THREE.Vector3(.9,-1.2,this.data?.derived?1.65:.9);
    this.frameBounds(this.bounds,direction);
  }

  pick(event) {
    if (!this.pointerDown || Math.hypot(event.clientX-this.pointerDown[0], event.clientY-this.pointerDown[1]) > 5 || event.button !== 0) return;
    this.pointerDown = null;
    const bounds = this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2((event.clientX-bounds.left)/bounds.width*2-1, -(event.clientY-bounds.top)/bounds.height*2+1), this.camera);
    if(this.mode==='concept'){const record=this.concept?.pick(this.raycaster);if(record?.kind==='source')this.select(record.source_id);else if(record){this.selectedProposalId=record.id;this.applyAppearance();this.onProposalSelect(record);}return;}
    const active = this.highlightsEnabled && this.highlightIds.size > 0;
    const meshes = [...this.meshes.values()].filter((mesh) => mesh.visible && (!active || this.highlightIds.has(mesh.userData.elementId)));
    const hit = this.raycaster.intersectObjects(meshes, false).find(hit=>!hit.object.material.clippingPlanes?.some(plane=>plane.distanceToPoint(hit.point)<0));
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
  render() {this.needsRender=true;this.camera.updateMatrixWorld();this.positionAnnotations();}
  getSnapshot() {
    return {theme:this.theme,camera_state:this.getCameraState(),last_focus:this.lastFocus||null,mode:this.mode,cutaway:this.cutaway,cutaway_percent:this.cutawayPercent,clipping_references:(this.data?.floors||[]).map(f=>({id:f.id,...this.clippingReference(f.id)})),concept_build_count:this.conceptBuildCount,concept_records:[...(this.concept?.records.values() || [])],concept_placements:this.concept?.placements || {},render_info:{calls:this.renderer.info.render.calls,triangles:this.renderer.info.render.triangles,frames:this.renderCount},camera_target:this.controls.target.toArray(),revision_changes:this.revisionChanges,building_id:this.data?.building_id,revision_id:this.data?.revision_id,revision_number:this.data?.revision_number,document_id:this.data?.document_id, mesh_count:this.meshes.size, element_count:this.elements.size, selected_id:this.selectedId, highlight_ids:[...this.highlightIds], highlights_enabled:this.highlightsEnabled, show_assumptions:this.showAssumptions, floor_filter:this.floorFilter, exploded:this.exploded, camera_position:this.camera.position.toArray(), up_axis:this.camera.up.toArray(), annotations:this.annotations.map((item)=>({element_ids:item.elementIds,floor_id:item.floorId,floor_level:item.floorLevel,visible:!item.button.hidden})), elements:[...this.meshes].map(([id,mesh])=>({id,visible:mesh.visible,opacity:mesh.material.opacity,clipping_planes:(mesh.material.clippingPlanes||[]).map(p=>p.constant),display_offset_z:mesh.position.z-mesh.userData.baseZ}))};
  }
  clearGeometry() {
    if(this.concept){this.scene.remove(this.concept.group);this.concept.dispose();this.concept=null;}
    for (const mesh of this.meshes.values()) { mesh.geometry.dispose(); mesh.material.dispose(); for (const edge of mesh.children) { edge.geometry.dispose(); edge.material.dispose(); } }
    this.meshes.clear();
    this.group.clear();
    this.annotations=[];
    this.annotationLayer.replaceChildren();
  }
  dispose() { this.renderer.setAnimationLoop(null); this.resizeObserver.disconnect(); this.controls.dispose(); this.clearGeometry(); this.renderer.dispose(); this.renderer.domElement.remove(); this.annotationLayer.remove(); }
}
