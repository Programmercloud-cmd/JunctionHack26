import * as THREE from 'three';

// Presentation only. Nothing in this module is serialized, sent to QA, or
// inserted into the source element catalogue. Original mesh buffers are read-only.
export class ConceptLayer {
  constructor(data, sourceMeshes, placements = {}) {
    this.group = new THREE.Group();
    this.group.name = 'concept-presentation';
    this.data = data;
    this.sourceMeshes = sourceMeshes;
    this.floors = new Map();
    this.materials = new Set();
    this.geometries = new Set();
    this.textures = new Set();
    this.cuts = [];
    this.cutaway = false; this.cutawayPercent = 100;
    this.decorations = 0;
    this.records = new Map();
    this.placements = structuredClone(placements);
    this.sourceRings = new Map();
    const frames = new Map((data.floors || []).map(f => {
      const a=f.building_transform||[[1,0,0],[0,1,0],[0,0,1]],b=f.transform;
      return [f.id,b?a.map(row=>[0,1,2].map(j=>row.reduce((sum,v,k)=>sum+v*b[k][j],0))):null];
    }));
    for (const entry of data.comparison || []) {
      const matrix=frames.get(entry.floor_id);
      if (!matrix) continue;
      this.sourceRings.set(entry.element_id,(entry.polygons || []).map(ring => ring.map(([x,y]) => [matrix[0][0]*x+matrix[0][1]*y+matrix[0][2],matrix[1][0]*x+matrix[1][1]*y+matrix[1][2]])));
    }
    this.builtAt = performance.now();
    try {
    this.makePalette();
    for (const [id, mesh] of [...sourceMeshes].sort(([a],[b])=>a.localeCompare(b))) {
      const element = data.elements.find(e => e.id === id);
      const key = element.storey_id || '';
      if (!this.floors.has(key)) {
        const group = new THREE.Group();
        this.group.add(group);
        this.floors.set(key, {id:key,group, bounds:new THREE.Box3(), elements:[], plane:null});
      }
      const floor = this.floors.get(key);
      const box = this.originalBounds(mesh);
      floor.bounds.union(box);
      floor.elements.push({element, mesh, box});
    }
    for (const floor of this.floors.values()) this.buildFloor(floor);
    for(const floor of this.floors.values())this.batchFloor(floor);
    this.buildLighting();
    this.buildMs = performance.now() - this.builtAt;
    } catch(error) {this.dispose();throw error;}
  }

  own(geometry) { this.geometries.add(geometry); return geometry; }
  recordSource(element, fallback = false) {
    const record={id:element.id,kind:'source',source_id:element.id,floor_id:element.storey_id,
      label:element.name || element.id, fallback,
      note:fallback ? 'Source-associated schematic fallback: precise styling is unavailable for this footprint. Materials and vertical appearance are display assumptions.' : 'Source-associated geometry. Concept materials, body details, facing and heights are display assumptions, not source facts.'};
    this.records.set(record.id,record);return record;
  }
  tag(group, record) {group.traverse(mesh=>{if(mesh.isMesh)mesh.userData.conceptRecord=record.id;});}
  rectangleFrame(element) {
    const rings=this.sourceRings.get(element.id);
    if (!rings || rings.length!==1) return null;
    let ring=rings[0].slice(0,-1);
    ring=ring.filter((point,i)=>{const a=ring[(i+ring.length-1)%ring.length],b=ring[(i+1)%ring.length];return Math.abs((point[0]-a[0])*(b[1]-point[1])-(point[1]-a[1])*(b[0]-point[0]))>1e-9;});
    if(ring.length!==4)return null;
    const [a,b,c,d]=ring,ab=[b[0]-a[0],b[1]-a[1]],bc=[c[0]-b[0],c[1]-b[1]],w=Math.hypot(...ab),h=Math.hypot(...bc);
    if(!w||!h||Math.abs(ab[0]*bc[0]+ab[1]*bc[1])>w*h*1e-6||Math.hypot(a[0]+c[0]-b[0]-d[0],a[1]+c[1]-b[1]-d[1])>Math.max(w,h)*1e-6)return null;
    return {x:(a[0]+c[0])/2,y:(a[1]+c[1])/2,w,d:h,angle:Math.atan2(ab[1],ab[0])};
  }
  fitWithin(group,w,d) {
    const b=new THREE.Box3().setFromObject(group),size=b.getSize(new THREE.Vector3()),center=b.getCenter(new THREE.Vector3());
    // Normalize decorative overhangs into the supported rectangle; never grow source bounds.
    group.scale.x=Math.min(1,w/Math.max(size.x,1e-12));group.scale.y=Math.min(1,d/Math.max(size.y,1e-12));
    for(const child of group.children){child.position.x-=center.x;child.position.y-=center.y;}
  }
  registerProposal(floor,item,key,group,label) {
    const record={id:`proposal:${item.element.id}:${key}`,kind:'proposal',source_id:null,host_id:item.element.id,
      floor_id:item.element.storey_id,label,note:'Decorative proposal, not depicted source evidence. Placement and dimensions are display choices; excluded from QA and IFC export.'};
    this.records.set(record.id,record);this.tag(group,record);
    // Amber outlines distinguish proposed furnishings from source-associated objects.
    group.traverse(mesh=>{if(mesh.isMesh){const edge=new THREE.LineSegments(this.own(new THREE.EdgesGeometry(mesh.geometry,35)),new THREE.LineBasicMaterial({color:0xb97818,transparent:true,opacity:.65}));this.materials.add(edge.material);mesh.add(edge);}});
    floor.group.add(group);this.decorations++;return record;
  }
  material(params) { const m = new THREE.MeshStandardMaterial(params); this.materials.add(m); return m; }
  makePalette() {
    const canvas = document.createElement('canvas'); canvas.width=512; canvas.height=512;
    const c = canvas.getContext('2d');
    c.fillStyle='#b89062'; c.fillRect(0,0,512,512);
    for (let p=0;p<8;p++) {
      const tone = 171 + (p*17%27);
      c.fillStyle=`rgb(${tone+24},${tone},${tone-40})`; c.fillRect(0,p*64,512,63);
      c.strokeStyle='rgba(66,43,24,.15)'; c.lineWidth=1;
      for (let i=0;i<14;i++) {
        c.beginPath(); const y=p*64+4+i*4.1;
        c.moveTo(0,y); c.bezierCurveTo(180,y+Math.sin(i+p)*3,340,y-2,512,y+1); c.stroke();
      }
      c.fillStyle='rgba(60,40,22,.18)'; c.fillRect((p*197)%512,p*64,1,64);
    }
    this.woodTexture = new THREE.CanvasTexture(canvas);
    this.woodTexture.wrapS = this.woodTexture.wrapT = THREE.RepeatWrapping;
    this.woodTexture.colorSpace = THREE.SRGBColorSpace;
    this.woodTexture.anisotropy = 4;
    this.textures.add(this.woodTexture);
    this.palette = {
      plaster:this.material({color:0xece6d9,roughness:.88}),
      cap:this.material({color:0xf4eddf,roughness:.85,side:THREE.DoubleSide}),
      oak:this.material({color:0xc8a477,roughness:.58}),
      wood:this.material({color:0xffffff,map:this.woodTexture,roughness:.63,side:THREE.DoubleSide}),
      stone:this.material({color:0xc6c5b9,roughness:.85,side:THREE.DoubleSide}),
      linen:this.material({color:0xe9e0cf,roughness:.96}),
      sage:this.material({color:0x738673,roughness:.91}),
      dark:this.material({color:0x323d37,roughness:.62}),
      metal:this.material({color:0x9b8a62,roughness:.3,metalness:.68}),
      ceramic:this.material({color:0xf3f1e7,roughness:.24}),
      water:this.material({color:0x779a9b,roughness:.2,metalness:.25}),
      leaf:this.material({color:0x426b46,roughness:.9}),
      leafLight:this.material({color:0x79945d,roughness:.87}),
      pot:this.material({color:0xc9a587,roughness:.9}),
      rug:this.material({color:0xd8cbbb,roughness:1}),
      glass:this.material({color:0xa4c5cb,roughness:.12,metalness:.18,transparent:true,opacity:.35,depthWrite:false,side:THREE.DoubleSide}),
      light:this.material({color:0xffedc7,emissive:0xffce83,emissiveIntensity:.55,roughness:.45})
    };
  }
  originalBounds(mesh) {
    mesh.geometry.computeBoundingBox();
    const matrix = new THREE.Matrix4().compose(new THREE.Vector3(mesh.position.x,mesh.position.y,mesh.userData.baseZ),mesh.quaternion,mesh.scale);
    return mesh.geometry.boundingBox.clone().applyMatrix4(matrix);
  }
  box(parent,w,d,h,x,y,z,material,radius=0) {
    let geometry;
    if (radius>0) {
      const r=Math.min(radius,w/3,d/3), shape=new THREE.Shape();
      shape.moveTo(-w/2+r,-d/2); shape.lineTo(w/2-r,-d/2); shape.quadraticCurveTo(w/2,-d/2,w/2,-d/2+r);
      shape.lineTo(w/2,d/2-r);shape.quadraticCurveTo(w/2,d/2,w/2-r,d/2);shape.lineTo(-w/2+r,d/2);shape.quadraticCurveTo(-w/2,d/2,-w/2,d/2-r);shape.lineTo(-w/2,-d/2+r);shape.quadraticCurveTo(-w/2,-d/2,-w/2+r,-d/2);
      geometry=this.own(new THREE.ExtrudeGeometry(shape,{depth:h,bevelEnabled:false,curveSegments:3}));
      geometry.translate(0,0,-h/2);
    } else geometry=this.own(new THREE.BoxGeometry(w,d,h));
    const mesh=new THREE.Mesh(geometry,material);mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;
  }
  cylinder(parent,r1,r2,h,x,y,z,material,segments=16) {
    const geometry=this.own(new THREE.CylinderGeometry(r1,r2,h,segments));geometry.rotateX(Math.PI/2);
    const mesh=new THREE.Mesh(geometry,material);mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;
  }
  sphere(parent,x,y,z,sx,sy,sz,material) {
    const mesh=new THREE.Mesh(this.own(new THREE.SphereGeometry(1,10,7)),material);mesh.scale.set(sx,sy,sz);mesh.position.set(x,y,z);mesh.castShadow=true;parent.add(mesh);return mesh;
  }
  feet(parent,w,d,h,u) {for(const x of [-w*.36,w*.36])for(const y of [-d*.36,d*.36])this.cylinder(parent,u*.025,u*.02,h,x,y,h/2,this.palette.dark,8);}

  furnish(parent,type,w,d,u) {
    const p=this.palette;
    const h=.72*u;
    if (type==='bed') {
      this.box(parent,w*.98,d*.98,.22*u,0,0,.13*u,p.oak,.035*u);
      this.box(parent,w*.94,d*.93,.22*u,0,0,.33*u,p.linen,.09*u);
      this.box(parent,w*.96,d*.64,.045*u,0,-d*.14,.46*u,p.sage,.03*u);
      this.box(parent,w,.06*u,.75*u,0,d*.46,.4*u,p.oak,.02*u);
      for(const x of [-w*.24,w*.24])this.box(parent,w*.4,d*.2,.09*u,x,d*.32,.48*u,p.ceramic,.055*u);
    } else if(type==='table') {
      this.feet(parent,w,d,h,u);this.box(parent,w,d,.065*u,0,0,h,p.oak,.08*u);
      this.cylinder(parent,.07*u,.06*u,.14*u,0,0,h+.09*u,p.pot);
      this.sphere(parent,0,0,h+.23*u,.11*u,.1*u,.11*u,p.leaf);
    } else if(type==='chair') {
      this.feet(parent,w,d,.42*u,u);this.box(parent,w,d,.09*u,0,0,.46*u,p.sage,.05*u);
      this.box(parent,w,.065*u,.33*u,0,d*.42,.64*u,p.oak,.015*u);
    } else if(type==='cabinet') {
      this.box(parent,w,d,.83*u,0,0,.43*u,p.sage,.015*u);
      this.box(parent,w*1.02,d*1.02,.055*u,0,0,.87*u,p.ceramic,.015*u);
      const n=Math.max(1,Math.round(w/(.55*u)));
      for(let i=0;i<n;i++) {
        this.box(parent,w/n*.92,.012*u,.68*u,-w/2+(i+.5)*w/n,-d/2-.006*u,.44*u,p.sage);
        this.box(parent,.13*u,.025*u,.016*u,-w/2+(i+.5)*w/n,-d/2-.025*u,.72*u,p.metal);
      }
    } else if(type==='sink') {
      this.box(parent,w,d,.8*u,0,0,.4*u,p.oak);
      this.box(parent,w*1.02,d*1.02,.1*u,0,0,.85*u,p.ceramic,.05*u);
      this.box(parent,w*.7,d*.65,.015*u,0,0,.905*u,p.water,.06*u);
      this.cylinder(parent,.016*u,.016*u,.22*u,0,d*.3,.98*u,p.metal,8);
      this.box(parent,.025*u,d*.3,.025*u,0,d*.17,1.08*u,p.metal);
    } else if(type==='toilet') {
      this.cylinder(parent,w*.24,w*.2,.36*u,0,-d*.05,.18*u,p.ceramic);
      this.sphere(parent,0,-d*.08,.38*u,w*.43,d*.36,.12*u,p.ceramic);
      this.sphere(parent,0,-d*.09,.47*u,w*.27,d*.22,.015*u,p.water);
      this.box(parent,w*.8,d*.22,.65*u,0,d*.35,.34*u,p.ceramic,.04*u);
    } else if(type==='shower') {
      this.box(parent,w,d,.07*u,0,0,.04*u,p.ceramic);
      this.box(parent,w,.018*u,1.55*u,0,d*.47,.81*u,p.glass);
      this.cylinder(parent,.018*u,.018*u,1.65*u,w*.34,d*.4,.85*u,p.metal,8);
      this.cylinder(parent,.13*u,.13*u,.025*u,w*.25,d*.3,1.66*u,p.metal);
    } else if(type==='appliance') {
      this.box(parent,w,d,.82*u,0,0,.43*u,p.ceramic,.02*u);
      // A generic appliance label does not establish a hob, fridge or washer.
      this.box(parent,w*.92,d*.92,.035*u,0,0,.86*u,p.stone,.02*u);
    } else if(type==='sofa') {
      this.feet(parent,w,d,.14*u,u);
      this.box(parent,w,d,.27*u,0,0,.28*u,p.sage,.08*u);
      this.box(parent,w,.16*u,.5*u,0,d*.4,.53*u,p.sage,.055*u);
      for(const x of [-w*.45,w*.45])this.box(parent,w*.1,d,.38*u,x,0,.43*u,p.sage,.04*u);
      for(const x of [-w*.23,w*.23])this.box(parent,w*.43,d*.72,.1*u,x,-d*.06,.46*u,p.linen,.05*u);
      this.box(parent,w*.19,d*.23,.14*u,w*.29,d*.1,.59*u,p.oak,.055*u);
    } else if(type==='bench') {
      this.feet(parent,w,d,.42*u,u);this.box(parent,w,d,.09*u,0,0,.46*u,p.oak,.02*u);
      for(let i=0;i<5;i++)this.box(parent,w,d/6,.014*u,0,-d*.4+i*d*.2,.515*u,p.oak);
    }
  }
  plant(parent,x,y,z,u) {
    const p=this.palette;
    this.cylinder(parent,.19*u,.14*u,.33*u,x,y,z+.165*u,p.pot);
    this.cylinder(parent,.17*u,.17*u,.02*u,x,y,z+.33*u,p.dark);
    this.cylinder(parent,.025*u,.035*u,.55*u,x,y,z+.56*u,p.oak,8);
    for(let i=0;i<7;i++) {
      const a=i*2.4;
      const leaf=this.sphere(parent,x+Math.cos(a)*.14*u,y+Math.sin(a)*.14*u,z+(.57+i*.055)*u,.21*u,.085*u,.15*u,i%2?p.leaf:p.leafLight);
      leaf.rotation.z=a;
    }
    this.decorations++;
  }

  buildFloor(floor) {
    const p=this.palette, bounds=floor.bounds, size=bounds.getSize(new THREE.Vector3());
    const wallHeights=floor.elements.filter(x=>x.element.kind==='wall').map(x=>x.box.max.z-x.box.min.z).sort((a,b)=>a-b);
    const wallHeight=wallHeights[Math.floor(wallHeights.length/2)] || Math.max(size.x,size.y)*.14;
    floor.unit=this.data.units==='m'?1:wallHeight/2.7;
    const u=floor.unit;
    floor.base=Math.min(...floor.elements.map(x=>x.box.min.z));
    const floorZ=floor.elements.find(x=>['room','outdoor'].includes(x.element.kind))?.box.max.z ?? floor.base;
    const metadata=(this.data.floors||[]).find(f=>f.id===floor.id);
    const reference=metadata || (!floor.id?this.data.uncontained_reference:null);
    floor.referenceBase=Number.isFinite(reference?.base_elevation)?reference.base_elevation:bounds.min.z;
    floor.referenceHeight=Number.isFinite(reference?.reference_height)?reference.reference_height:size.z;
    floor.cutHeight=floor.referenceBase+floor.referenceHeight;
    floor.plane=new THREE.Plane(new THREE.Vector3(0,0,-1),floor.cutHeight);
    const occupied=floor.elements.filter(x=>!['room','outdoor','open_edge'].includes(x.element.kind)).map(x=>x.box.clone());
    floor.occupied=occupied;
    for(const {element,mesh,box} of floor.elements) {
      if(!this.data.derived && element.kind==='room' && element.geometry.type!=='floor')continue;
      const isFeature=this.data.derived && ['furniture','fixture'].includes(element.kind) && ['bed','table','chair','cabinet','sink','toilet','shower','appliance'].includes(element.semantic_type);
      const frame=isFeature?this.rectangleFrame(element):null;
      const record=this.recordSource(element,isFeature&&!frame);
      if(isFeature && frame) {
        const g=new THREE.Group();
        this.furnish(g,element.semantic_type,frame.w,frame.d,u);
        this.fitWithin(g,frame.w,frame.d);g.position.set(frame.x,frame.y,floorZ+.012*u);g.rotation.z=frame.angle;
        this.tag(g,record);floor.group.add(g);continue;
      }
      let material=p.plaster;
      if(element.kind==='room')material=/KPH|KHH|PH|Tekn|bath|wash|sauna/i.test(element.name)?p.stone:p.wood;
      if(element.kind==='outdoor')material=p.wood;
      if(element.kind==='door'||element.kind==='stairs'||/bench/i.test(element.name))material=p.oak;
      if(element.kind==='window')material=p.glass;
      if(element.kind==='railing')material=p.dark;
      if(element.kind==='open_edge')material=p.stone;
      let geometry=mesh.geometry;
      if(material===p.wood) {
        geometry=this.own(mesh.geometry.clone());
        const pos=geometry.attributes.position,uv=[];
        for(let i=0;i<pos.count;i++)uv.push(pos.getX(i)/(u*2.8),pos.getY(i)/(u*2.8));
        geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
      }
      const clone=new THREE.Mesh(geometry,material);clone.position.copy(mesh.position);clone.position.z=mesh.userData.baseZ;clone.quaternion.copy(mesh.quaternion);clone.scale.copy(mesh.scale);
      clone.userData.sourceElementId=element.id;
      clone.userData.conceptRecord=record.id;
      clone.castShadow=element.kind!=='window';clone.receiveShadow=true;floor.group.add(clone);
      // Glazing uses its exact source mesh; unsupported frame profiles are not added.
      // Keep existing level stair/bench schematics. Concept mode cannot establish ascent or facing.
    }
    if(this.data.derived) {
      for(const item of floor.elements.filter(x=>x.element.kind==='outdoor'))this.outdoor(floor,item,u);
      // Room size alone does not establish residential use (hall/temple/church etc.).
      for(const item of floor.elements.filter(x=>x.element.kind==='room' && /^(OH\b|living room\b)/i.test(x.element.name.trim())))this.lounge(floor,item,u);
    }
    // A thin shadow receiver is purely a display surface; it never closes room boundaries.
    const ground=this.box(floor.group,size.x+u*.8,size.y+u*.8,.04*u,(bounds.min.x+bounds.max.x)/2,(bounds.min.y+bounds.max.y)/2,floor.base-.09*u,this.material({color:0xe5e1d6,roughness:1}),.11*u);
    ground.castShadow=false;ground.userData.presentationOnly=true;
  }
  sectionCap(mesh,height,material) {
    mesh.updateMatrix();
    const positions=mesh.geometry.attributes.position,index=mesh.geometry.index,segments=[];
    const count=index?index.count:positions.count;
    for(let i=0;i<count;i+=3) {
      const points=[0,1,2].map(j=>new THREE.Vector3().fromBufferAttribute(positions,index?index.getX(i+j):i+j).applyMatrix4(mesh.matrix));
      const hits=[];
      for(let j=0;j<3;j++) {const a=points[j],b=points[(j+1)%3];if((a.z<height)!==(b.z<height)){const t=(height-a.z)/(b.z-a.z);hits.push(new THREE.Vector2(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t));}}
      if(hits.length===2&&hits[0].distanceTo(hits[1])>1e-8)segments.push(hits);
    }
    const shapes=[];
    while(segments.length) {
      const chain=segments.pop();let matched=true;
      while(matched) {matched=false;for(let i=0;i<segments.length;i++){const s=segments[i],last=chain[chain.length-1];if(last.distanceTo(s[0])<1e-5||last.distanceTo(s[1])<1e-5){chain.push(last.distanceTo(s[0])<1e-5?s[1]:s[0]);segments.splice(i,1);matched=true;break;}}}
      if(chain.length>3&&chain[0].distanceTo(chain[chain.length-1])<1e-5)shapes.push(new THREE.Shape(chain));
    }
    if(!shapes.length)return null;
    const cap=new THREE.Mesh(this.own(new THREE.ShapeGeometry(shapes)),material);cap.position.z=height+.0001;cap.receiveShadow=true;return cap;
  }
  inside(item,x,y) {
    const geometry=item.mesh.geometry,p=geometry.attributes.position,ind=geometry.index;
    const matrix=new THREE.Matrix4().compose(new THREE.Vector3(item.mesh.position.x,item.mesh.position.y,item.mesh.userData.baseZ),item.mesh.quaternion,item.mesh.scale);
    for(let i=0;i<(ind?ind.count:p.count);i+=3) {
      const a=[0,1,2].map(j=>new THREE.Vector3().fromBufferAttribute(p,ind?ind.getX(i+j):i+j).applyMatrix4(matrix));
      const cross=(q,r)=>(r.x-q.x)*(y-q.y)-(r.y-q.y)*(x-q.x);
      const v=[cross(a[0],a[1]),cross(a[1],a[2]),cross(a[2],a[0])];
      const area=(a[1].x-a[0].x)*(a[2].y-a[0].y)-(a[1].y-a[0].y)*(a[2].x-a[0].x);
      if(Math.abs(area)>1e-10 && (v.every(n=>n>=-1e-7)||v.every(n=>n<=1e-7)))return true;
    }
    return false;
  }
  fits(item,x,y,w,d) {
    if(![-.5,.5].every(dx=>[-.5,.5].every(dy=>this.inside(item,x+dx*w,y+dy*d))))return false;
    const rings=this.sourceRings.get(item.element.id);
    if(!rings?.length)return false;
    const left=x-w/2,right=x+w/2,bottom=y-d/2,top=y+d/2,eps=1e-8;
    // A contour crossing the candidate's interior detects concavities and holes,
    // including a small hole that would be missed by sampling corner/center points.
    for(const ring of rings)for(let i=1;i<ring.length;i++) {
      const a=ring[i-1],b=ring[i],delta=[b[0]-a[0],b[1]-a[1]];
      let low=0,high=1;
      for(const [axis,min,max]of [[0,left+eps,right-eps],[1,bottom+eps,top-eps]]) {
        if(Math.abs(delta[axis])<eps){if(a[axis]<min||a[axis]>max){high=-1;break;}}
        else {const ts=[(min-a[axis])/delta[axis],(max-a[axis])/delta[axis]].sort((p,q)=>p-q);low=Math.max(low,ts[0]);high=Math.min(high,ts[1]);}
      }
      if(low<high)return false;
    }
    return true;
  }
  place(floor,item,w,d,preferY=.5,key='default') {
    const b=item.box;
    const ledgerKey=`${item.element.id}:${key}`,signature=JSON.stringify(item.element.geometry);
    const prior=this.placements[ledgerKey];
    const candidates=[[.5,preferY],[.22,preferY],[.78,preferY],[.22,.25],[.78,.25],[.22,.75],[.78,.75],[.5,.5]];
    const positions=candidates.map(([fx,fy])=>({x:b.min.x+w/2+(b.max.x-b.min.x-w)*fx,y:b.min.y+d/2+(b.max.y-b.min.y-d)*fy}));
    if(prior?.signature===signature)positions.unshift(prior);
    for(const {x,y}of positions) {
      if(!this.fits(item,x,y,w,d))continue;
      const rect=new THREE.Box3(new THREE.Vector3(x-w/2,y-d/2,b.max.z),new THREE.Vector3(x+w/2,y+d/2,b.max.z+floor.unit));
      if(floor.occupied.some(o=>o.max.x>rect.min.x&&o.min.x<rect.max.x&&o.max.y>rect.min.y&&o.min.y<rect.max.y))continue;
      floor.occupied.push(rect);this.placements[ledgerKey]={signature,x,y,w,d};return {x,y};
    }
    return null;
  }
  outdoor(floor,item,u) {
    const w=Math.min(1.6*u,(item.box.max.x-item.box.min.x)*.68),d=Math.min(2.2*u,(item.box.max.y-item.box.min.y)*.7);
    const spot=/terrace|balcony|terassi|parveke/i.test(item.element.name)?this.place(floor,item,w,d,.5,'terrace'):null;
    if(spot) {
      const g=new THREE.Group();
      const table=new THREE.Group();g.add(table);this.furnish(table,'table',w*.7,d*.35,u);
      for(const y of [-d*.34,d*.34]){const chair=new THREE.Group();chair.position.y=y;if(y<0)chair.rotation.z=Math.PI;g.add(chair);this.furnish(chair,'chair',w*.4,d*.25,u);}
      this.fitWithin(g,w,d);g.position.set(spot.x,spot.y,item.box.max.z+.01*u);this.registerProposal(floor,item,'terrace',g,'Proposed terrace table and chairs');
    }
    for(const [key,fy]of [['plant-a',.9],['plant-b',.1]]) {
      const spot=this.place(floor,item,.8*u,.8*u,fy,key);
      if(spot){const g=new THREE.Group();this.plant(g,0,0,0,u);this.fitWithin(g,.8*u,.8*u);g.position.set(spot.x,spot.y,item.box.max.z);this.registerProposal(floor,item,key,g,'Proposed planting');}
    }
  }
  lounge(floor,item,u) {
    const b=item.box;
    const hasBed=floor.elements.some(x=>x.element.semantic_type==='bed'&&b.containsPoint(x.box.getCenter(new THREE.Vector3()).setZ(b.max.z)));
    if(!hasBed && (b.max.x-b.min.x)>2.8*u&&(b.max.y-b.min.y)>2.6*u) {
      const w=2.4*u,d=2.05*u,spot=this.place(floor,item,w,d,.72,'lounge');
      if(spot) {
        const g=new THREE.Group();
        this.box(g,w,d,.012*u,0,0,.008*u,this.palette.rug,.08*u);
        const sofa=new THREE.Group();sofa.position.y=d*.25;g.add(sofa);this.furnish(sofa,'sofa',w*.92,d*.43,u);
        this.cylinder(g,.39*u,.39*u,.045*u,0,-d*.27,.39*u,this.palette.oak);
        this.cylinder(g,.13*u,.18*u,.37*u,0,-d*.27,.19*u,this.palette.dark);
        this.cylinder(g,.065*u,.065*u,.07*u,.1*u,-d*.27,.45*u,this.palette.ceramic);
        this.fitWithin(g,w,d);g.position.set(spot.x,spot.y,b.max.z+.01*u);this.registerProposal(floor,item,'lounge',g,'Proposed lounge arrangement');
      }
    }
    const spot=this.place(floor,item,.8*u,.8*u,.85,'plant');
    if(spot){const g=new THREE.Group();this.plant(g,0,0,0,u*.85);this.fitWithin(g,.8*u,.8*u);g.position.set(spot.x,spot.y,b.max.z);this.registerProposal(floor,item,'plant',g,'Proposed planting');}
  }
  batchFloor(floor) {
    // Merge static presentation meshes by material once, reducing draw calls
    // without dropping objects or changing any source buffers.
    floor.group.updateMatrixWorld(true);
    const batches=new Map(),caps=new Set(this.cuts.map(c=>c.cap).filter(Boolean));
    floor.group.traverse(mesh=>{
      if(!mesh.isMesh||caps.has(mesh)||mesh.children.some(child=>child.isLineSegments))return;
      const key=`${mesh.material.uuid}:${mesh.userData.conceptRecord || 'display'}`;
      if(!batches.has(key))batches.set(key,[]);
      batches.get(key).push(mesh);
    });
    for(const meshes of batches.values()) {
      if(meshes.length<2)continue;
      const material=meshes[0].material;
      const positions=[],normals=[],uvs=[],indices=[];
      for(const mesh of meshes) {
        const g=mesh.geometry,p=g.attributes.position,n=g.attributes.normal,uv=g.attributes.uv,offset=positions.length/3;
        const normalMatrix=new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld);
        for(let i=0;i<p.count;i++) {
          const v=new THREE.Vector3().fromBufferAttribute(p,i).applyMatrix4(mesh.matrixWorld);positions.push(v.x,v.y,v.z);
          const normal=n?new THREE.Vector3().fromBufferAttribute(n,i).applyMatrix3(normalMatrix).normalize():new THREE.Vector3(0,0,1);normals.push(normal.x,normal.y,normal.z);
          uvs.push(uv?uv.getX(i):0,uv?uv.getY(i):0);
        }
        for(let i=0;i<(g.index?g.index.count:p.count);i++)indices.push(offset+(g.index?g.index.getX(i):i));
        mesh.removeFromParent();
      }
      const geometry=this.own(new THREE.BufferGeometry());geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));geometry.setIndex(indices);
      const merged=new THREE.Mesh(geometry,material);merged.castShadow=!material.transparent;merged.receiveShadow=true;floor.group.add(merged);
      merged.userData.conceptRecord=meshes[0].userData.conceptRecord;
    }
  }
  pick(raycaster) {
    const meshes=[];
    for(const floor of this.floors.values())if(floor.group.visible)floor.group.traverse(mesh=>{if(mesh.isMesh&&mesh.visible&&mesh.userData.conceptRecord)meshes.push(mesh);});
    for(const hit of raycaster.intersectObjects(meshes,false)) {
      if(hit.object.material.clippingPlanes?.some(plane=>plane.distanceToPoint(hit.point)<0))continue;
      return this.records.get(hit.object.userData.conceptRecord);
    }
    return null;
  }
  applyAppearance(highlights,enabled,selected,showAssumptions) {
    const active=enabled&&highlights.size>0;
    this.group.traverse(mesh=>{
      const record=this.records.get(mesh.userData.conceptRecord);if(!mesh.isMesh||!record)return;
      if(!mesh.userData.appearanceBase){const previous=mesh.material;mesh.material=mesh.material.clone();for(const cut of this.cuts)if(cut.material===previous)cut.material=mesh.material;this.materials.add(mesh.material);mesh.userData.appearanceBase={color:mesh.material.color.clone(),opacity:mesh.material.opacity,transparent:mesh.material.transparent,depthWrite:mesh.material.depthWrite};}
      const base=mesh.userData.appearanceBase,highlight=record.kind==='source'&&highlights.has(record.source_id);
      mesh.material.color.copy(base.color);
      if(active&&highlight)mesh.material.color.setHex(0xcce979);
      else if(showAssumptions&&(record.kind==='proposal'||this.data.elements.find(e=>e.id===record.source_id)?.assumptions.length))mesh.material.color.setHex(0xe4ae55);
      mesh.material.opacity=active && !highlight ? .1 : base.opacity;
      mesh.material.transparent=mesh.material.opacity<1||base.transparent;mesh.material.depthWrite=mesh.material.opacity<1?false:base.depthWrite;
      mesh.material.emissive.setHex(selected===record.id?0x493015:0);mesh.material.emissiveIntensity=.25;
      for(const edge of mesh.children)if(edge.isLineSegments)edge.material.opacity=active && !highlight ? .04 : .65;
    });
  }
  buildLighting() {
    this.lights=new THREE.Group();this.group.add(this.lights);
    const hemi=new THREE.HemisphereLight(0xeaf0ff,0x92816a,2.1);hemi.position.set(0,0,20);this.lights.add(hemi);
    this.sun=new THREE.DirectionalLight(0xffe6bf,3.1);this.sun.castShadow=true;
    this.sun.shadow.mapSize.set(2048,2048);this.sun.shadow.bias=-.00015;this.sun.shadow.normalBias=.018;
    this.sun.shadow.radius=3;this.lights.add(this.sun);this.lights.add(this.sun.target);
    const fill=new THREE.DirectionalLight(0xdfeaff,1.1);fill.position.set(-5,-2,8);this.lights.add(fill);
  }
  syncVisibility(floorFilter,exploded,separation,floorIndices) {
    const bounds=new THREE.Box3();
    for(const [id,f]of this.floors) {
      f.group.visible=!floorFilter||floorFilter===id;
      f.group.position.z=exploded?(floorIndices.get(id)||0)*separation:0;
      f.plane.constant=f.cutHeight+f.group.position.z;
      if(f.group.visible)bounds.union(f.bounds.clone().translate(new THREE.Vector3(0,0,f.group.position.z)));
    }
    if(!bounds.isEmpty()) {
      const center=bounds.getCenter(new THREE.Vector3()),extent=Math.max(...bounds.getSize(new THREE.Vector3()).toArray(),1);
      this.sun.position.copy(center).add(new THREE.Vector3(-.35,-.7,1.4).multiplyScalar(extent));this.sun.target.position.copy(center);
      Object.assign(this.sun.shadow.camera,{left:-extent*.8,right:extent*.8,top:extent*.8,bottom:-extent*.8,near:extent*.02,far:extent*5});this.sun.shadow.camera.updateProjectionMatrix();
      this.sun.shadow.needsUpdate=true;
    }
    this.group.updateMatrixWorld(true);
    return bounds;
  }
  setCutaway(enabled) {this.setCutawayPercent(enabled?38:100);}
  setCutawayPercent(percent) {
    this.cutawayPercent=percent;this.cutaway=percent<100;
    for(const floor of this.floors.values()){
      floor.cutHeight=floor.referenceBase+floor.referenceHeight*percent/100;
      floor.plane.constant=floor.cutHeight+floor.group.position.z;
      floor.group.traverse(mesh=>{
        if(!mesh.material)return;
        if(!mesh.userData.clippingMaterial){mesh.material=mesh.material.clone();this.materials.add(mesh.material);mesh.userData.clippingMaterial=true;}
        mesh.material.clippingPlanes=percent<100?[floor.plane]:[];mesh.material.clipShadows=true;mesh.material.needsUpdate=true;
      });
    }
  }
  dispose() {for(const g of this.geometries)g.dispose();for(const m of this.materials)m.dispose();for(const t of this.textures)t.dispose();this.sun?.shadow.dispose();this.group.clear();}
}
