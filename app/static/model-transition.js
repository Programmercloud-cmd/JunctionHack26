import * as THREE from 'three';

const HOLD_MS = 350;
const ROLL_MS = 1900;
const TILT_MS = 1260;
const SILHOUETTE_MS = 2600;
const SILHOUETTE_MORPH_MS = 1120;
const SILHOUETTE_RISE_MS = 1050;
const PENDING_PHASES = ['gable','compound','tower'];
const GROW_MS = 2050;
const MODEL_HOLD_MS = 650;
const SETTLE_MS = 750;
const PEEL_MS = 2400;
const FIT_MS = 500;
const ROLL_END = HOLD_MS + ROLL_MS;
const TILT_END = ROLL_END + TILT_MS;
const PLAN_WIDTH = 346;
const PLAN_HEIGHT = 279;
const CLOTH_HEM = 18;
const GRID_SIZE = 11.25;
const COLUMNS = 58;
const ROWS = 48;
const MIN_STRETCH = .82;
const MAX_STRETCH = 1.19;
const FLAT_FABRIC = [48,100,177];
const clamp = (value) => Math.max(0, Math.min(1, value));
const ease = (value) => {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
};
const glide = (value) => {
  const t = clamp(value);
  return t * t * t * (10 + t * (-15 + 6 * t));
};
const lerp = (from, to, t) => from + (to - from) * t;
const rgb = (red,green,blue) => 'rgb(' + [red,green,blue].map(Math.round).join(',') + ')';
const PALETTE = Array.from({length:65},(_,index) => {
  const light = index / 64;
  return rgb(lerp(14,58,light),lerp(53,113,light),lerp(110,196,light));
});
const fabricColor = (light) => PALETTE[Math.round(clamp(light) * 64)];

function inverse(matrix) {
  if (!matrix || matrix.length !== 3) return null;
  const [[a,b,c],[d,e,f]] = matrix;
  const det = a * e - b * d;
  if (!Number.isFinite(det) || det === 0) return null;
  return {
    areaScale: 1 / Math.abs(det),
    point: (x,y) => [(e * (x - c) - b * (y - f)) / det, (-d * (x - c) + a * (y - f)) / det],
  };
}

function sourceWalls(scene, page, width, height) {
  if (!scene?.derived) return [];
  const frames = new Map();
  for (const floor of scene.floors || []) {
    if (floor.source?.page !== page) continue;
    const placement = inverse(floor.building_transform);
    const source = inverse(floor.transform);
    if (placement && source) frames.set(floor.id, {
      point: (x,y) => source.point(...placement.point(x,y)),
      base: floor.base_elevation || 0,
      verticalScale: Math.sqrt(source.areaScale * placement.areaScale * width * height),
    });
  }
  const meshes = [];
  for (const item of scene.elements || []) {
    const frame = frames.get(item.storey_id);
    const mesh = item.geometry;
    if (!frame || mesh?.type !== 'mesh' || item.kind !== 'wall' || item.representation === 'unresolved') continue;
    const points = new Float32Array(mesh.positions.length);
    for (let i = 0; i < points.length; i += 3) {
      const [u,v] = frame.point(mesh.positions[i], mesh.positions[i + 1]);
      const z = (mesh.positions[i + 2] - frame.base) * frame.verticalScale;
      points[i] = (u - .5) * width;
      points[i + 1] = (v - .5) * height;
      points[i + 2] = z;
    }
    meshes.push({points, indices:mesh.indices});
  }
  return meshes;
}

function sheet(width, height) {
  const left = -width / 2 - CLOTH_HEM;
  const top = -height / 2 - CLOTH_HEM;
  const stepX = -2 * left / COLUMNS;
  const stepY = -2 * top / ROWS;
  const stride = COLUMNS + 1;
  const nodes = [];
  const indices = [], links = [];
  const uv = [], points = new Float32Array(stride * (ROWS + 1) * 3);
  for (let row = 0; row <= ROWS; row++) {
    for (let column = 0; column <= COLUMNS; column++) {
      const x = left + stepX * column, y = top + stepY * row;
      const u = column / COLUMNS, v = row / ROWS;
      const perimeter = Math.pow(2 * Math.max(Math.abs(u - .5), Math.abs(v - .5)), 2.5);
      const overhang = Math.max(0, Math.abs(x) - width / 2, Math.abs(y) - height / 2);
      const restZ = 2.6 - Math.min(5, overhang * .24) +
        .72 * Math.sin(u * 18 + v * 9) * perimeter +
        .35 * Math.sin(u * 15 + v * 5) * Math.sin(v * 13 - u * 5);
      const index = row * stride + column;
      nodes.push({x,y,u,v,perimeter,restZ,edgeAllowance:edgeAllowance(u,v)});
      points.set([x,y,restZ], index * 3);
      uv.push(column * stepX / GRID_SIZE, row * stepY / GRID_SIZE);
      if (column < COLUMNS) links.push([index * 3, (index + 1) * 3, stepX]);
      if (row < ROWS) links.push([index * 3, (index + stride) * 3, stepY]);
      if (row < ROWS && column < COLUMNS) {
        const next = index + stride;
        indices.push(index, index + 1, next + 1, index, next + 1, next);
        const diagonal = Math.hypot(stepX,stepY);
        links.push([index * 3, (next + 1) * 3, diagonal], [(index + 1) * 3, next * 3, diagonal]);
      }
    }
  }
  return {left,top,stepX,stepY,nodes,points,uv,indices,links,preferredZ:new Float32Array(nodes.length)};
}

function silhouetteProfile(index) {
  const footprint = (x,y,halfX,halfY,falloff) => 1 - ease(Math.hypot(
    Math.max(0,Math.abs(x) - halfX),Math.max(0,Math.abs(y) - halfY)) / falloff);
  const gable = (x,y,halfX,halfY,eave,ridge) =>
    lerp(ridge,eave,clamp(Math.abs(y) / halfY)) * footprint(x,y,halfX,halfY,17);
  return (x,y) => {
    if (index === 0) return Math.max(gable(y,x,49,43,34,67),83 * footprint(x - 20,y + 25,9,10,9));
    if (index === 1) return Math.max(gable(x,y + 17,78,48,45,86),gable(y - 27,x - 37,48,29,43,79),
      96 * footprint(x + 38,y + 34,10,11,10));
    return 94 * footprint(x,y,32,30,20);
  };
}

function clothAxis(halfLength, profile) {
  const intervals = 512;
  const length = new Float32Array(intervals + 1);
  const step = 2 * halfLength / intervals;
  let previous = profile(-halfLength);
  for (let i = 1; i <= intervals; i++) {
    const next = profile(i * step - halfLength);
    length[i] = length[i - 1] + Math.hypot(step,next - previous);
    previous = next;
  }
  return (offset) => {
    const distance = length[intervals / 2] + offset;
    let left = 0, right = intervals;
    while (right - left > 1) {
      const middle = (left + right) >> 1;
      if (length[middle] < distance) left = middle;
      else right = middle;
    }
    const fraction = clamp((distance - length[left]) / (length[right] - length[left]));
    return (left + fraction) * step - halfLength;
  };
}

function fitPendingSilhouette(cloth, index) {
  const profile = silhouetteProfile(index);
  const fitX = clothAxis(-cloth.left,x => profile(x,0));
  const fitY = clothAxis(-cloth.top,y => profile(0,y));
  const preferred = new Float64Array(cloth.points.length);
  for (const [i,node] of cloth.nodes.entries()) {
    const x = lerp(node.x,fitX(node.x),lerp(.58,1,1 - ease((Math.abs(node.y) - 42) / 105)));
    const y = lerp(node.y,fitY(node.y),lerp(.58,1,1 - ease((Math.abs(node.x) - 44) / 125)));
    preferred.set([x,y,profile(x,y)],i * 3);
  }
  // The approved wait-stage shapes use free, extension-only material links.
  const fitted = preferred.slice();
  const {links} = cloth;
  for (let pass = 0; pass < 64; pass++) {
    for (let edge = 0; edge < links.length; edge++) {
      const [a,b,rest] = links[pass % 2 === 0 ? edge : links.length - 1 - edge];
      const x = fitted[b] - fitted[a], y = fitted[b + 1] - fitted[a + 1], z = fitted[b + 2] - fitted[a + 2];
      const length = Math.sqrt(x * x + y * y + z * z);
      if (length <= rest) continue;
      const correction = .44 * (length - rest) / length;
      fitted[a] += x * correction; fitted[b] -= x * correction;
      fitted[a + 1] += y * correction; fitted[b + 1] -= y * correction;
      fitted[a + 2] += z * correction; fitted[b + 2] -= z * correction;
    }
    const contact = pass < 44 ? .18 : .05;
    for (let i = 0; i < fitted.length; i += 3) {
      fitted[i] = lerp(fitted[i],preferred[i],.05);
      fitted[i + 1] = lerp(fitted[i + 1],preferred[i + 1],.05);
      fitted[i + 2] = lerp(fitted[i + 2],preferred[i + 2],contact);
    }
  }
  return fitted;
}

function pendingPose(cloth, elapsed, poses) {
  const time = Math.max(0,elapsed - TILT_END);
  const index = Math.floor(time / SILHOUETTE_MS) % PENDING_PHASES.length;
  const within = time % SILHOUETTE_MS;
  const morph = glide((within - SILHOUETTE_MS + SILHOUETTE_MORPH_MS) / SILHOUETTE_MORPH_MS);
  const rise = glide(time / SILHOUETTE_RISE_MS);
  const nextIndex = (index + 1) % PENDING_PHASES.length;
  const from = poses[index], to = poses[nextIndex] || from;
  const amplitudes = [.48,.78,1.05];
  const tension = rise * lerp(amplitudes[index],amplitudes[nextIndex],morph);
  const ripple = (1 + 1.3 * tension) * ease((elapsed - ROLL_END) / 350);
  for (const [index,node] of cloth.nodes.entries()) {
    const i = index * 3;
    cloth.points[i] = from ? lerp(node.x,lerp(from[i],to[i],morph),rise) : node.x;
    cloth.points[i + 1] = from ? lerp(node.y,lerp(from[i + 1],to[i + 1],morph),rise) : node.y;
    const edge = Math.pow(2 * Math.max(Math.abs(node.u - .5),Math.abs(node.v - .5)),4);
    const support = from ? lerp(from[i + 2],to[i + 2],morph) * rise : 0;
    cloth.points[i + 2] = 2.2 + support + Math.sin(node.u * 17 + node.v * 9) * edge * ripple;
  }
  return {
    phase:PENDING_PHASES[morph > .5 ? nextIndex : index],
    held:rise === 1 && morph === 0 ? index : null,
  };
}

function carpetPosition(cloth, view, elapsed, shortSide) {
  const progress = clamp((elapsed - HOLD_MS) / ROLL_MS);
  const advance = lerp(ease(progress),glide(progress),.45);
  const {top} = cloth;
  const radius = Math.min(shortSide * .14,19) * Math.sqrt(1 - advance) * (1 - ease((advance - .87) / .13));
  const outside = Math.min(top - 25,-view.y / view.scale - 24);
  return {front:lerp(outside,-top,advance),radius,progress};
}

function paintCarpet(context, cloth, view, {front,radius,progress}) {
  const {left,top} = cloth;
  const width = -2 * left;
  const fabric = fabricColor;
  const grid = (draw) => {
    context.beginPath();
    draw();
    context.strokeStyle = '#f4f8ff98';
    context.lineWidth = .58 / view.scale;
    context.stroke();
  };
  context.save();
  context.transform(view.scale,0,0,view.scale,view.x,view.y);
  if (front > top) {
    context.fillStyle = fabric(.78);
    context.fillRect(left,top,width,front - top);
    grid(() => {
      for (let x = left; x <= -left + .01; x += GRID_SIZE) {
        context.moveTo(x,top); context.lineTo(x,front);
      }
      for (let y = top; y <= front; y += GRID_SIZE) {
        context.moveTo(left,y); context.lineTo(-left,y);
      }
    });
  }
  if (radius > .15) {
    const shadowDepth = Math.min(8,radius * .48);
    const contact = front + radius - shadowDepth / 2;
    const shadow = context.createLinearGradient(0,contact,0,contact + shadowDepth);
    shadow.addColorStop(0,'rgba(5,17,38,' + Math.min(.20,radius * .015) + ')');
    shadow.addColorStop(1,'#05112600');
    context.fillStyle = shadow;
    context.fillRect(left,contact,width,shadowDepth);

    const lighting = context.createLinearGradient(0,front - radius,0,front + radius);
    lighting.addColorStop(0,fabric(.63)); lighting.addColorStop(.34,fabric(1));
    lighting.addColorStop(.59,fabric(.84)); lighting.addColorStop(.86,fabric(.42));
    lighting.addColorStop(1,fabric(.10));
    const bow = Math.min(radius * .3,1.5) * (1 - glide(progress));
    const edge = (x) => Math.sin((x - left) / width * Math.PI) * bow;
    context.beginPath();
    context.moveTo(left,front - radius);
    context.quadraticCurveTo(0,front - radius + bow * 1.6,-left,front - radius);
    context.lineTo(-left,front + radius);
    context.quadraticCurveTo(0,front + radius + bow * 1.6,left,front + radius);
    context.closePath();
    context.fillStyle = lighting;
    context.fill();
    context.clip();
    grid(() => {
      for (let x = left; x <= -left + .01; x += GRID_SIZE) {
        const bend = edge(x);
        context.moveTo(x,front - radius + bend); context.lineTo(x,front + radius + bend);
      }
      // A grid row stays attached to the material as it rotates around the roll.
      const firstY = front + radius * Math.PI / 2;
      const lastY = Math.min(-top,front + radius * Math.PI * 1.5);
      const firstGridY = top + Math.max(0,Math.ceil((firstY - top) / GRID_SIZE)) * GRID_SIZE;
      for (let y = firstGridY; y <= lastY; y += GRID_SIZE) {
        const wrapped = front - radius * Math.sin((y - front) / radius);
        context.moveTo(left,wrapped);
        context.quadraticCurveTo(0,wrapped + bow * 1.6,-left,wrapped);
      }
    });
  }
  context.restore();
}

function wallSurface(meshes, cloth) {
  // Rasterize the actual upper triangles of the projected IFC walls, including
  // the reach of a cloth triangle whose corners straddle a thin wall top.
  const columns = COLUMNS * 2 + 1, rows = ROWS * 2 + 1;
  const sx = cloth.stepX / 2, sy = cloth.stepY / 2;
  const heights = new Float32Array(columns * rows);
  const radius = Math.hypot(sx,sy) * 1.65;
  const radius2 = radius * radius;
  for (const {points,indices} of meshes) {
    for (let i = 0; i < indices.length; i += 3) {
      const a = indices[i] * 3, b = indices[i + 1] * 3, c = indices[i + 2] * 3;
      const ax = points[a], ay = points[a + 1], az = points[a + 2];
      const bx = points[b], by = points[b + 1], bz = points[b + 2];
      const cx = points[c], cy = points[c + 1], cz = points[c + 2];
      const area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
      if (Math.abs(area) < 1e-5 || Math.max(az,bz,cz) <= 0) continue;
      const firstX = Math.max(0, Math.ceil((Math.min(ax,bx,cx) - cloth.left - radius) / sx));
      const lastX = Math.min(columns - 1, Math.floor((Math.max(ax,bx,cx) - cloth.left + radius) / sx));
      const firstY = Math.max(0, Math.ceil((Math.min(ay,by,cy) - cloth.top - radius) / sy));
      const lastY = Math.min(rows - 1, Math.floor((Math.max(ay,by,cy) - cloth.top + radius) / sy));
      const edges = [[ax,ay,az,bx,by,bz], [bx,by,bz,cx,cy,cz], [cx,cy,cz,ax,ay,az]];
      for (let row = firstY; row <= lastY; row++) {
        const y = cloth.top + row * sy;
        for (let col = firstX; col <= lastX; col++) {
          const x = cloth.left + col * sx;
          const u = ((x - ax) * (cy - ay) - (y - ay) * (cx - ax)) / area;
          const v = ((bx - ax) * (y - ay) - (by - ay) * (x - ax)) / area;
          let z = u >= 0 && v >= 0 && u + v <= 1 ? az + u * (bz - az) + v * (cz - az) : 0;
          if (z === 0) {
            for (const [ex,ey,ez,fx,fy,fz] of edges) {
              const dx = fx - ex, dy = fy - ey;
              const t = clamp(((x - ex) * dx + (y - ey) * dy) / (dx * dx + dy * dy || 1));
              if ((x - ex - t * dx) ** 2 + (y - ey - t * dy) ** 2 <= radius2) {
                z = Math.max(z, lerp(ez,fz,t));
              }
            }
          }
          const index = row * columns + col;
          heights[index] = Math.max(heights[index], z);
        }
      }
    }
  }
  // Spread support away from a ridge at a shallow slope, so the sheet can
  // bridge adjacent walls without fitting each sharp edge like a skin.
  const horizontalFall = sx * .59, verticalFall = sy * .59;
  const diagonalFall = Math.hypot(horizontalFall,verticalFall);
  for (const direction of [1,-1]) {
    const start = direction === 1 ? 0 : rows * columns - 1;
    for (let index = start; index >= 0 && index < heights.length; index += direction) {
      const previousRow = index - direction * columns;
      const column = index % columns;
      if (column - direction >= 0 && column - direction < columns) {
        heights[index] = Math.max(heights[index], heights[index - direction] - horizontalFall);
      }
      if (previousRow < 0 || previousRow >= heights.length) continue;
      heights[index] = Math.max(heights[index], heights[previousRow] - verticalFall);
      if (column > 0) heights[index] = Math.max(heights[index], heights[previousRow - 1] - diagonalFall);
      if (column < columns - 1) heights[index] = Math.max(heights[index], heights[previousRow + 1] - diagonalFall);
    }
  }
  return (x,y) => {
    const px = (x - cloth.left) / sx, py = (y - cloth.top) / sy;
    const col = Math.floor(px), row = Math.floor(py);
    if (col < 0 || row < 0 || col >= columns - 1 || row >= rows - 1) return 0;
    const index = row * columns + col, across = px - col;
    return lerp(lerp(heights[index],heights[index + 1],across),
      lerp(heights[index + columns],heights[index + columns + 1],across),py - row);
  };
}

function relaxFabric(cloth, {passes = 42, fixedHem = false, heightTarget} = {}) {
  const {points,links,nodes,preferredZ} = cloth;
  for (let i = 0; i < nodes.length; i++) preferredZ[i] = points[i * 3 + 2];
  const supportedPasses = Math.round(passes * 26 / 42);
  for (let pass = 0; pass < passes; pass++) {
    const forward = pass % 2 === 0;
    for (let edge = 0; edge < links.length; edge++) {
      const [a,b,rest] = links[forward ? edge : links.length - 1 - edge];
      const x = points[b] - points[a], y = points[b + 1] - points[a + 1], z = points[b + 2] - points[a + 2];
      const distance = Math.sqrt(x * x + y * y + z * z);
      if (distance < 1e-6) continue;
      const stiffness = distance > rest ? .49 : .24;
      const adjustment = stiffness * (distance - rest) / distance;
      const shiftA = fixedHem && !nodes[a / 3].edgeAllowance ? 0 : adjustment;
      const shiftB = fixedHem && !nodes[b / 3].edgeAllowance ? 0 : adjustment;
      points[a] += x * shiftA; points[b] -= x * shiftB;
      points[a + 1] += y * shiftA; points[b + 1] -= y * shiftB;
      points[a + 2] += z * shiftA; points[b + 2] -= z * shiftB;
    }
    if (pass >= supportedPasses) continue;
    for (let index = 0; index < nodes.length; index++) {
      if (fixedHem && !nodes[index].edgeAllowance) continue;
      const i = index * 3;
      const target = heightTarget?.(points[i],points[i + 1],nodes[index]) ?? preferredZ[index];
      points[i + 2] = lerp(points[i + 2],target,.036);
    }
  }
  correctExcessStrain(cloth,fixedHem);
}

function materialWithinRange({points,indices,stepX,stepY}, strength) {
  const base = 1 - strength;
  for (let i = 0; i < indices.length; i += 3) {
    // Choose canonical +X/+Y differences from either half of the material cell.
    const a = indices[i] * 3, b = indices[i + 1] * 3, c = indices[i + 2] * 3;
    const xStart = i % 6 ? c : a, xEnd = b;
    const yStart = i % 6 ? a : b, yEnd = c;
    const ux = base + strength * (points[xEnd] - points[xStart]) / stepX;
    const uy = strength * (points[xEnd + 1] - points[xStart + 1]) / stepX;
    const uz = strength * (points[xEnd + 2] - points[xStart + 2]) / stepX;
    const vx = strength * (points[yEnd] - points[yStart]) / stepY;
    const vy = base + strength * (points[yEnd + 1] - points[yStart + 1]) / stepY;
    const vz = strength * (points[yEnd + 2] - points[yStart + 2]) / stepY;
    const uu = ux * ux + uy * uy + uz * uz;
    const vv = vx * vx + vy * vy + vz * vz;
    const uv = ux * vx + uy * vy + uz * vz;
    const spread = Math.sqrt((uu - vv) ** 2 + 4 * uv * uv);
    if (ux * vy <= uy * vx || (uu + vv - spread) / 2 < MIN_STRETCH ** 2 ||
        (uu + vv + spread) / 2 > MAX_STRETCH ** 2) return false;
  }
  return true;
}

function correctExcessStrain(cloth, fixedHem) {
  if (materialWithinRange(cloth,1)) return;
  // Guard the occasional extreme wall/support pose after the free-edge solve.
  // Material UVs remain attached to the same vertices.
  let low = 0, high = 1;
  for (let attempt = 0; attempt < 8; attempt++) {
    const mid = (low + high) / 2;
    if (materialWithinRange(cloth,mid)) low = mid;
    else high = mid;
  }
  const {nodes,points} = cloth;
  const offsetX = fixedHem ? 0 : (points[0] + points[points.length - 3]) / 2;
  const offsetY = fixedHem ? 0 : (points[1] + points[points.length - 2]) / 2;
  const offsetZ = fixedHem ? 0 : (points[2] + points[points.length - 1]) / 2;
  for (const [index,node] of nodes.entries()) {
    const i = index * 3;
    points[i] = lerp(node.x + offsetX,points[i],low);
    points[i + 1] = lerp(node.y + offsetY,points[i + 1],low);
    points[i + 2] = lerp(offsetZ,points[i + 2],low);
  }
}

function conformToWalls(cloth, surface) {
  const pose = cloth.points.slice();
  const heightTarget = (x,y,node) => Math.max(node.restZ, (surface?.(x,y) || 0) + 2.4);
  for (const [index,node] of cloth.nodes.entries()) {
    cloth.points.set([node.x,node.y,heightTarget(node.x,node.y,node)], index * 3);
  }
  relaxFabric(cloth,{heightTarget});
  const fitted = cloth.points.slice();
  cloth.points.set(pose);
  return fitted;
}

function sameWallPose(first, second) {
  if (!first || first.length !== second.length) return false;
  return first.every((value,index) => value === second[index]);
}

function fitOverModel(view, cloth, bounds, blend, turned) {
  if (!bounds || ![bounds.minX,bounds.minY,bounds.maxX,bounds.maxY].every(Number.isFinite) ||
      bounds.maxX <= bounds.minX || bounds.maxY <= bounds.minY) return;
  // The sheet's border encloses the projected viewer bounds, including every
  // visible floor. Fit in the tilted cloth plane, not to the page AABB.
  const halfW = (bounds.maxX - bounds.minX) / 2 + 14;
  const halfH = (bounds.maxY - bounds.minY) / 2 + 14;
  const tiltClearance = Math.min(view.width / (halfW * 2), view.height / (halfH * 2));
  const rotation = glide((tiltClearance - 1.10) / .26);
  const endPitch = lerp(.99,.84,rotation);
  const envelope = (yaw) => {
    const cos = Math.abs(Math.cos(yaw)), sin = Math.abs(Math.sin(yaw));
    const scale = Math.max(view.scale, (cos * halfW + sin * halfH / endPitch) / -cloth.left,
      (sin * halfW + cos * halfH / endPitch) / -cloth.top);
    return {yaw,scale};
  };
  const unturned = envelope(lerp(-.008,-.15,rotation));
  let end = turned ? envelope(turned) : unturned;
  if (turned === null && Math.sign(halfW - halfH) !== Math.sign(cloth.top - cloth.left)) {
    // Turn a long sheet toward the longer screen axis when that costs less
    // blank cloth than enlarging it. The fit turns while it still fully covers.
    for (const angle of [-Math.PI / 3,-Math.PI / 2]) {
      const candidate = envelope(angle);
      if (candidate.scale < end.scale * .94) end = candidate;
    }
  }
  view.scale = lerp(view.scale,end.scale,blend);
  const yaw = lerp(Math.atan2(view.sin,view.cos),end.yaw,blend);
  const pitch = lerp(Math.acos(view.pitch),Math.acos(endPitch),blend);
  view.cos = Math.cos(yaw); view.sin = Math.sin(yaw);
  view.pitch = Math.cos(pitch); view.rise = Math.sin(pitch);
  view.x = lerp(view.x,(bounds.minX + bounds.maxX) / 2,blend);
  view.y = lerp(view.y,(bounds.minY + bounds.maxY) / 2,blend);
  return {turned:end === unturned ? 0 : end.yaw};
}

function edgeAllowance(u,v) {
  const nearestEdge = Math.min(u,1 - u,v,1 - v);
  return glide(nearestEdge / .16);
}

function squareHem(cloth, amount) {
  // Keep the border closed over the viewer envelope. Interior folds keep the
  // fitted wall silhouette and the same fixed fabric coordinates.
  for (const [index,node] of cloth.nodes.entries()) {
    const i = index * 3;
    const settle = amount * (1 - node.edgeAllowance);
    cloth.points[i] = lerp(cloth.points[i],node.x,settle);
    cloth.points[i + 1] = lerp(cloth.points[i + 1],node.y,settle);
    cloth.points[i + 2] *= 1 - settle;
  }
  relaxFabric(cloth,{passes:18,fixedHem:amount >= 1});
}

const vertex = `
  varying vec2 coordinates;
  varying vec3 facing;
  void main() {
    coordinates = uv;
    facing = normal;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
const fabricFragment = `
  uniform vec3 flatFabric;
  uniform float contourLight;
  varying vec2 coordinates;
  varying vec3 facing;
  void main() {
    vec3 normal = normalize(facing);
    float light = max(0.0, dot(normal, normalize(vec3(-.48,-.81,.68))));
    vec2 fine = coordinates * vec2(43.0,37.0);
    vec2 weave = sin(fine * 6.28318) * max(vec2(0.0), 1.0 - 2.0 * fwidth(fine));
    vec3 shaded = mix(vec3(.055,.20,.43), vec3(.20,.44,.78), light) * (1.0 + weave.x * weave.y * .025);
    vec3 fabric = mix(flatFabric, shaded, contourLight);
    vec2 cell = abs(fract(coordinates + .5) - .5);
    vec2 edge = max(fwidth(coordinates) * .55, vec2(.001));
    vec2 lines = 1.0 - smoothstep(vec2(.014) - edge, vec2(.014) + edge, cell);
    vec3 shadedThread = mix(vec3(.56,.65,.77), vec3(.96,.98,1.0), .45 + .55 * light);
    vec3 printColor = mix(vec3(.957,.973,1.0), shadedThread, contourLight);
    gl_FragColor = vec4(mix(fabric, printColor, max(lines.x,lines.y) * mix(.596,.72,contourLight)), 1.0);
  }
`;
function createGL(canvas, cloth) {
  const context = canvas.getContext('webgl2', {alpha:true, antialias:true, depth:true});
  if (!context) return null;
  const renderer = new THREE.WebGLRenderer({canvas, context, alpha:true, antialias:true});
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const group = new THREE.Group();
  group.matrixAutoUpdate = false;
  scene.add(group);
  const camera = new THREE.OrthographicCamera();
  camera.position.z = 10000;
  camera.far = 20000;
  const clothGeometry = new THREE.BufferGeometry();
  clothGeometry.setAttribute('position', new THREE.BufferAttribute(cloth.points, 3).setUsage(THREE.DynamicDrawUsage));
  clothGeometry.setAttribute('uv', new THREE.Float32BufferAttribute(cloth.uv, 2));
  clothGeometry.setIndex(cloth.indices);
  const clothMesh = new THREE.Mesh(clothGeometry, new THREE.ShaderMaterial({
    vertexShader:vertex, fragmentShader:fabricFragment, side:THREE.DoubleSide,
    uniforms:{flatFabric:{value:new THREE.Vector3(...FLAT_FABRIC.map(value => value / 255))},contourLight:{value:0}},
  }));
  clothMesh.frustumCulled = false;
  group.add(clothMesh);
  return {
    render(view, width, height, pixelRatio, clothVisible) {
      if (renderer.getPixelRatio() !== pixelRatio || canvas.width !== Math.floor(width * pixelRatio) ||
          canvas.height !== Math.floor(height * pixelRatio)) {
        renderer.setPixelRatio(pixelRatio);
        renderer.setSize(width,height,false);
      }
      camera.left = -width / 2; camera.right = width / 2;
      camera.top = height / 2; camera.bottom = -height / 2; camera.updateProjectionMatrix();
      const {scale, cos, sin, pitch, rise, x, y, liftOffset} = view;
      group.matrix.set(
        scale * cos, -scale * sin, 0, x - width / 2,
        -scale * pitch * sin, -scale * pitch * cos, scale * rise, height / 2 - y + liftOffset,
        rise * sin, rise * cos, pitch, 0,
        0, 0, 0, 1,
      );
      group.matrixWorldNeedsUpdate = true;
      clothMesh.visible = clothVisible;
      if (clothVisible) {
        clothMesh.material.uniforms.contourLight.value = ease(view.tilt * 2);
        clothGeometry.attributes.position.needsUpdate = true;
        clothGeometry.computeVertexNormals();
      }
      renderer.render(scene,camera);
    },
    dispose(releaseContext = true) {
      clothGeometry.dispose(); clothMesh.material.dispose();
      renderer.dispose();
      if (releaseContext) renderer.forceContextLoss();
    },
  };
}

function polygon(context, points, fill, stroke = '') {
  context.beginPath();
  points.forEach(([x,y], index) => index ? context.lineTo(x,y) : context.moveTo(x,y));
  context.closePath();
  context.fillStyle = fill;
  context.fill();
  if (stroke) { context.strokeStyle = stroke; context.lineWidth = .75; context.stroke(); }
}

function drawPlan(context, view, width, height, image, shadow) {
  const {x,y,scale} = view;
  const left = x - width * scale / 2, top = y - height * scale / 2;
  context.save();
  context.shadowColor = 'rgba(34,54,83,' + shadow * .196 + ')';
  context.shadowBlur = 13;
  context.shadowOffsetY = 5;
  context.fillStyle = '#fff';
  context.fillRect(left,top,width * scale,height * scale);
  context.restore();
  if (image.complete && image.naturalWidth) {
    context.imageSmoothingEnabled = true;
    context.drawImage(image,left,top,width * scale,height * scale);
  }
}

function drawCloth(context, view, cloth, coverModel) {
  const figures = [];
  const points = [];
  for (let i = 0; i < cloth.points.length; i += 3) {
    points.push(view.project(cloth.points[i],cloth.points[i + 1],cloth.points[i + 2]));
  }
  const stride = COLUMNS + 1;
  if (coverModel) {
    // Shared edges can leave fractional alpha even when both neighboring
    // cells are opaque. Protect the live viewer during the reveal.
    const perimeter = points.slice(0,stride);
    for (let row = 1; row <= ROWS; row++) perimeter.push(points[row * stride + COLUMNS]);
    for (let column = COLUMNS - 1; column >= 0; column--) perimeter.push(points[ROWS * stride + column]);
    for (let row = ROWS - 1; row > 0; row--) perimeter.push(points[row * stride]);
    polygon(context,perimeter,fabricColor(.78));
  }
  for (let row = 0; row < ROWS; row++) {
    for (let column = 0; column < COLUMNS; column++) {
      const first = row * stride + column;
      const ids = [first,first + 1,first + stride + 1,first + stride];
      const corners = ids.map(id => points[id]);
      if (corners.every(([x,y]) => x < -2) || corners.every(([x,y]) => y < -2) ||
          corners.every(([x,y]) => x > view.width + 2) || corners.every(([x,y]) => y > view.height + 2)) continue;
      const [a,b,c,d] = ids.map(id => id * 3);
      const mesh = cloth.points;
      const du = [0,1,2].map(i => mesh[b + i] + mesh[c + i] - mesh[a + i] - mesh[d + i]);
      const dv = [0,1,2].map(i => mesh[c + i] + mesh[d + i] - mesh[a + i] - mesh[b + i]);
      const nx = du[1] * dv[2] - du[2] * dv[1];
      const ny = du[2] * dv[0] - du[0] * dv[2];
      const nz = du[0] * dv[1] - du[1] * dv[0];
      const normalLight = (.78 * nz - .42 * nx - .47 * ny) / (Math.hypot(nx,ny,nz) || 1);
      figures.push({corners,row,column,depth:corners.reduce((sum,point) => sum + point[2],0),shade:fabricColor(normalLight)});
    }
  }
  figures.sort((a,b) => a.depth - b.depth);
  for (const {corners,row,column,shade} of figures) {
    polygon(context,corners,shade,shade);
    context.strokeStyle = view.dark ? '#eef6ff92' : '#f9fcff90';
    context.lineWidth = .54;
    const [a,b,c,d] = corners;
    const left = column * cloth.stepX, top = row * cloth.stepY;
    context.beginPath();
    for (let x = Math.ceil((left - 1e-6) / GRID_SIZE) * GRID_SIZE; x < left + cloth.stepX - 1e-6; x += GRID_SIZE) {
      const t = clamp((x - left) / cloth.stepX);
      context.moveTo(lerp(a[0],b[0],t),lerp(a[1],b[1],t));
      context.lineTo(lerp(d[0],c[0],t),lerp(d[1],c[1],t));
    }
    for (let y = Math.ceil((top - 1e-6) / GRID_SIZE) * GRID_SIZE; y < top + cloth.stepY - 1e-6; y += GRID_SIZE) {
      const t = clamp((y - top) / cloth.stepY);
      context.moveTo(lerp(a[0],d[0],t),lerp(a[1],d[1],t));
      context.lineTo(lerp(b[0],c[0],t),lerp(b[1],c[1],t));
    }
    context.stroke();
  }
}

export function createModelTransition(stage, {image, page, openingRect} = {}) {
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (motion.matches) return {
    setScene() {}, reveal: ({showModel} = {}) => Promise.resolve(showModel?.() === true), dispose() {},
  };
  const pageWidth = page?.width || image?.naturalWidth || PLAN_WIDTH;
  const pageHeight = page?.height || image?.naturalHeight || PLAN_HEIGHT;
  const factor = Math.min(PLAN_WIDTH / pageWidth,PLAN_HEIGHT / pageHeight);
  const width = pageWidth * factor, height = pageHeight * factor;
  const pageNumber = Number(typeof page === 'number' ? page : page?.page) || 1;
  const cloth = sheet(PLAN_WIDTH,PLAN_HEIGHT);
  const pendingShapes = [];
  const canvas = document.createElement('canvas');
  const glCanvas = document.createElement('canvas');
  for (const layer of [canvas,glCanvas]) {
    layer.setAttribute('aria-hidden','true');
    Object.assign(layer.style,{position:'absolute', inset:'0', width:'100%', height:'100%', pointerEvents:'none'});
    stage.append(layer);
  }
  const context = canvas.getContext('2d');
  // Keep the application's opening image until the module has a drawing surface.
  if (context && image?.parentElement === stage) image.remove();
  let gl;
  try { gl = context ? null : createGL(glCanvas,cloth); } catch { gl = null; }
  if (!gl) glCanvas.hidden = true;
  let disposed = false, animation = 0, result = null;
  let wallScene, wallPose, surface, startingShape, grownShape, peelShape, replacedPose, modelUnlocked = false;
  let growthStarts = null, fitStarts = null, peelStarts = null, turned = null;
  let resolveReveal, revealPromise, getModelBounds, showModel;
  let elapsed = 0, lastPaint = null;
  let heldFrame = '';
  let flatWide = openingRect?.stageWidth || null, flatHigh = openingRect?.stageHeight || null;
  const darkMode = window.matchMedia('(prefers-color-scheme: dark)');

  function finishReveal(success) {
    if (result !== null) return;
    result = success;
    cancelAnimationFrame(animation);
    animation = 0;
    resolveReveal?.(success);
  }

  function exposeModel() {
    try { if (!modelUnlocked) modelUnlocked = showModel?.() === true; }
    catch { modelUnlocked = false; }
    return modelUnlocked;
  }

  function projectedBounds() {
    try { return getModelBounds?.(); }
    catch { return null; }
  }

  function viewAt(w,h,tilt) {
    const defaultScale = Math.min((w - 32) / width,(h - 32) / height,1.65);
    if (flatWide === null) { flatWide = w; flatHigh = h; }
    const rectValid = openingRect?.width > 0 && openingRect?.height > 0;
    const flatScale = rectValid ? Math.min(openingRect.width * w / flatWide / width,
      openingRect.height * h / flatHigh / height) : defaultScale;
    const flatX = rectValid ? (openingRect.x + openingRect.width / 2) * w / flatWide : w / 2;
    const flatY = rectValid ? (openingRect.y + openingRect.height / 2) * h / flatHigh : h / 2;
    const tiltedScale = Math.min(w / 486,h / 362);
    const scale = lerp(Math.max(.02,flatScale),tiltedScale,tilt);
    const x = lerp(flatX,w * .5,tilt), y = lerp(flatY,h * .60,tilt);
    const pitch = lerp(1,.57,tilt), rise = Math.sqrt(1 - pitch * pitch);
    const angle = -.38 * tilt, cos = Math.cos(angle), sin = Math.sin(angle);
    return {scale,x,y,cos,sin,pitch,rise,tilt,dark:darkMode.matches,width:w,height:h,liftOffset:0,project(px,py,z = 0) {
      const forward = this.sin * px + this.cos * py;
      return [this.x + (this.cos * px - this.sin * py) * this.scale,
        this.y + (forward * this.pitch - z * this.rise) * this.scale - this.liftOffset,
        forward * this.rise + z * this.pitch];
    }};
  }

  function liftPose(view, peelTime, stageHeight) {
    const {nodes,points} = cloth;
    const overall = clamp(peelTime / PEEL_MS);
    const verticalTravel = Math.max(stageHeight * 1.3, view.y + Math.hypot(cloth.left,cloth.top) * view.scale + 24);
    const baseLift = glide((overall - .18) / .82);
    const settle = glide(overall);
    const curlHeight = 25;
    view.liftOffset = verticalTravel * baseLift + Math.max(0,peelTime - PEEL_MS) * .25;
    for (let index = 0; index < nodes.length; index++) {
      const node = nodes[index], i = index * 3;
      const {u,v,perimeter} = node;
      const delay = .34 * ((1 - u) * .63 + v * .37);
      const lift = glide((overall - delay) / .65);
      const curl = Math.sin(u * 5 - v * 2 + overall * 5) * 6 * lift * (1 - lift);
      const ripple = Math.sin(u * 7 - v * 5 + overall * 8) * perimeter * 1.4 * lift * (1 - lift);
      points[i] = lerp(peelShape[i],node.x - 17,settle) + curl * .65;
      points[i + 1] = lerp(peelShape[i + 1],node.y - 28,settle);
      points[i + 2] = lerp(peelShape[i + 2],node.restZ,settle) + curlHeight * (lift - baseLift) + curl + ripple;
    }
    if (overall > 0) relaxFabric(cloth,{passes:18});
    let largestScreenY = -Infinity;
    for (let i = 0; i < points.length; i += 3) largestScreenY = Math.max(largestScreenY,
      view.project(points[i],points[i + 1],points[i + 2])[1]);
    return largestScreenY;
  }

  function requestFrame() {
    if (!disposed && result === null && !animation && !document.hidden) animation = requestAnimationFrame(draw);
  }

  function draw(now) {
    animation = 0;
    if (disposed || result !== null) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) {
      lastPaint = null;
      if (revealPromise) finishReveal(false);
      return;
    }
    if (lastPaint !== null) {
      const frameTime = now - lastPaint;
      // Keep the opening readable after a slow frame. Once the loop starts,
      // its pace follows elapsed time even when painting misses frames.
      elapsed += elapsed < TILT_END ? Math.min(frameTime,100) : frameTime;
    }
    lastPaint = now;
    const tilt = glide((elapsed - ROLL_END) / TILT_MS);
    const view = viewAt(w,h,tilt);
    let phase = elapsed < HOLD_MS ? 'flat' : elapsed < ROLL_END ? 'rolling' : 'tilting';
    let held = null;
    if (elapsed >= ROLL_END && growthStarts === null) {
      // Spread the one-time fitting across tilt frames. Pending playback only
      // interpolates these fitted poses and keeps its material coordinates.
      if (pendingShapes.length < PENDING_PHASES.length && (!wallScene || elapsed < TILT_END)) {
        pendingShapes.push(fitPendingSilhouette(cloth,pendingShapes.length));
      }
      const pending = pendingPose(cloth,elapsed,pendingShapes);
      if (elapsed >= TILT_END) ({phase,held} = pending);
    }
    if (wallScene && elapsed >= TILT_END && growthStarts === null) {
      startingShape = replacedPose || cloth.points.slice();
      replacedPose = null;
      grownShape = wallPose;
      growthStarts = now;
    }
    if (growthStarts !== null && peelStarts === null) {
      held = null;
      const growthDuration = surface ? GROW_MS : SETTLE_MS;
      const grow = glide((now - growthStarts) / growthDuration);
      for (let i = 0; i < cloth.points.length; i++) cloth.points[i] = lerp(startingShape[i],grownShape[i],grow);
      // Both endpoints are already fitted. Blend material vertices directly so
      // publication cannot briefly flatten or crumple the reference pose.
      phase = grow < 1 ? 'growing' : 'covered';
      if (revealPromise && grow >= 1 && now - growthStarts >= growthDuration + MODEL_HOLD_MS - FIT_MS && fitStarts === null) fitStarts = now;
    }
    if (fitStarts !== null) {
      const fitted = glide((now - fitStarts) / FIT_MS);
      const fit = fitOverModel(view,cloth,projectedBounds(),fitted,turned);
      if (!fit) {
        finishReveal(false);
        return;
      }
      turned = fit.turned;
      if (peelStarts === null) {
        squareHem(cloth,fitted);
        if (fitted >= 1) {
          if (!exposeModel()) {
            finishReveal(false);
            return;
          }
          peelShape = cloth.points.slice();
          peelStarts = now;
        }
      }
    }
    const peel = peelStarts === null ? -1 : now - peelStarts;
    const bottom = peel >= 0 ? liftPose(view,peel,h) : Infinity;
    // The end of the projected hem, not a timer alone, releases the model.
    const clear = peel >= PEEL_MS && bottom < -4;
    const clothVisible = elapsed >= ROLL_END && bottom >= -4;
    const currentPhase = clear ? 'clear' : peel >= 0 ? 'lifting' : phase;
    if (stage.dataset.transitionPhase !== currentPhase) stage.dataset.transitionPhase = currentPhase;
    const pixelRatio = Math.min(window.devicePixelRatio || 1,2);
    const frameKey = held === null ? '' : `${held}:${w}:${h}:${pixelRatio}:${view.dark}`;
    if (frameKey && frameKey === heldFrame) { requestFrame(); return; }
    heldFrame = frameKey;
    const pixelW = Math.round(w * pixelRatio), pixelH = Math.round(h * pixelRatio);
    if (context && (!gl || elapsed < TILT_END)) {
      if (canvas.hidden) canvas.hidden = false;
      if (canvas.width !== pixelW || canvas.height !== pixelH) { canvas.width = pixelW; canvas.height = pixelH; }
      context.setTransform(pixelRatio,0,0,pixelRatio,0,0);
      context.clearRect(0,0,w,h);
      if (elapsed < HOLD_MS) drawPlan(context,view,width,height,image || {},1);
      else if (elapsed < ROLL_END) {
        const carpet = carpetPosition(cloth,view,elapsed,PLAN_HEIGHT);
        if (carpet.front < height / 2) {
          const shadow = glide((height / 2 - carpet.front) / Math.max(14,height * .16));
          drawPlan(context,view,width,height,image || {},shadow);
        }
        paintCarpet(context,cloth,view,carpet);
      }
      if (!gl && clothVisible) drawCloth(context,view,cloth,peel >= 0);
    } else if (context && !canvas.hidden) {
      canvas.hidden = true;
    }
    if (gl && elapsed >= ROLL_END) {
      try { gl.render(view,w,h,pixelRatio,clothVisible); }
      catch {
        fallBack();
        if (peel >= 0) { finishReveal(false); return; }
      }
    }
    if (clear) finishReveal(true);
    else if (phase !== 'covered' || revealPromise) requestFrame();
  }

  function fallBack() {
    gl?.dispose(false);
    gl = null;
    glCanvas.hidden = true;
    heldFrame = '';
  }
  function onContextLost(event) {
    event.preventDefault();
    fallBack();
    requestFrame();
  }
  function onVisibilityChange() {
    if (document.hidden) {
      cancelAnimationFrame(animation);
      animation = 0;
      lastPaint = null;
      if (revealPromise) finishReveal(false);
    } else requestFrame();
  }
  function onMotionChange(event) {
    if (event.matches) {
      stage.dataset.transitionPhase = 'clear';
      finishReveal(revealPromise ? exposeModel() : true);
      canvas.hidden = true;
      glCanvas.hidden = true;
    }
  }
  const observer = new ResizeObserver(requestFrame);
  observer.observe(stage);
  motion.addEventListener('change',onMotionChange);
  glCanvas.addEventListener('webglcontextlost',onContextLost);
  document.addEventListener('visibilitychange',onVisibilityChange);
  image?.addEventListener('load',requestFrame);
  requestFrame();

  return {
    setScene(scene) {
      if (disposed || result !== null || peelStarts !== null || wallScene === scene) return;
      wallScene = scene;
      const walls = sourceWalls(scene,pageNumber,width,height);
      const nextSurface = walls.length ? wallSurface(walls,cloth) : null;
      const nextPose = conformToWalls(cloth,nextSurface);
      if (sameWallPose(wallPose,nextPose)) return;
      if (growthStarts !== null) replacedPose = cloth.points.slice();
      wallPose = nextPose;
      surface = nextSurface;
      growthStarts = fitStarts = turned = null;
      requestFrame();
    },
    reveal(options = {}) {
      if (disposed || result !== null) return Promise.resolve(!disposed && result === true);
      if (!revealPromise) {
        ({getModelBounds, showModel} = options);
        if (document.hidden || !stage.clientWidth || !stage.clientHeight || !wallScene || typeof showModel !== 'function' ||
            typeof getModelBounds !== 'function' || (!context && !gl)) {
          finishReveal(false);
          return Promise.resolve(false);
        }
        revealPromise = new Promise(resolve => { resolveReveal = resolve; });
      }
      requestFrame();
      return revealPromise;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      finishReveal(false);
      cancelAnimationFrame(animation);
      observer.disconnect();
      motion.removeEventListener('change',onMotionChange);
      glCanvas.removeEventListener('webglcontextlost',onContextLost);
      document.removeEventListener('visibilitychange',onVisibilityChange);
      image?.removeEventListener('load',requestFrame);
      gl?.dispose();
      canvas.remove();
      glCanvas.remove();
      delete stage.dataset.transitionPhase;
    },
  };
}
