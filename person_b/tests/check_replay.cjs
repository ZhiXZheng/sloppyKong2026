// Exercise the exported playback code without a browser or third-party packages.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const payload = html.match(/<script id="replay-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
const elements = Object.fromEntries(ids.map(id => [id, {
  value: ({run:'0',speed:'1',extent:'focus',timeline:'0'})[id] || '',
  textContent: id === 'replay-data' ? payload : '', innerHTML:'', style:{}, attrs:{}, handlers:{},
  classList:{toggle(){}}, setAttribute(key,value){this.attrs[key]=value;},
  addEventListener(type,handler){this.handlers[type]=handler;}
}]));
let animation;
const context={document:{getElementById(id){assert.ok(elements[id],`Missing element ${id}`);return elements[id];}},
  window:{matchMedia(){return {matches:false};}}, requestAnimationFrame(callback){animation=callback;},console};
vm.runInNewContext(script,context,{timeout:1000});
const trigger=(id,type,value)=>{if(value!==undefined)elements[id].value=value;elements[id].handlers[type]({target:elements[id]});};
assert.equal(elements.tick.textContent,'Ready');
assert.match(elements.entities.innerHTML,/Courier drone/);
assert.match(elements.entities.innerHTML,/Team A/);
const initial=elements.entities.innerHTML;
trigger('step','click');
assert.match(elements.tick.textContent,/Tick 0/);
assert.notEqual(elements.entities.innerHTML,initial);
trigger('timeline','input','10');
assert.match(elements.droneStatus.textContent,/delivered at tick 9/);
assert.match(elements.events.innerHTML,/Delivered 1 observation/);
trigger('run','change','1');
assert.doesNotMatch(elements.entities.innerHTML,/Courier drone/);
assert.equal(elements.droneStatus.textContent,'Courier disabled');
trigger('extent','change','full');
assert.equal(elements.grid.attrs.viewBox,'0 0 1096 1096');
trigger('timeline','input',elements.timeline.max);
assert.match(elements.score.innerHTML,/2 <small>\/ 3 rescued/);
trigger('run','change','0');
assert.match(elements.score.innerHTML,/3 <small>\/ 3 rescued/);
trigger('restart','click');
trigger('play','click');animation(0);animation(100);
assert.equal(elements.play.textContent,'Pause');
assert.notEqual(elements.entities.innerHTML,initial);
trigger('play','click');
assert.equal(elements.play.textContent,'Play');
assert.doesNotMatch(elements.entities.innerHTML,/NaN|undefined/);
console.log('Replay controls, animation, delivery, run switching, grid extent and scores: OK');
