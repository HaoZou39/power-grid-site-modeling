import {solutionContext,requireSolutionContext} from "../../.tmp-problem-snapshot/map/solution_context.js";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {runInNewContext} from "node:vm";
import ts from "typescript";
import {SiteEdit} from "../../.tmp-problem-snapshot/map/site_edit.js";
import * as evaluation from "../../.tmp-problem-snapshot/map/pose_evaluation.js";
import {mergeReevaluation} from "../../.tmp-problem-snapshot/map/reevaluation_recovery.js";
const text = readFileSync(new URL("./map_workspace.tsx", import.meta.url), "utf8");
const tree = ts.createSourceFile("workspace.tsx", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let submit, finish, layerEffect;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === "scoreWaiting") submit = node.getText(tree);
  if (ts.isCallExpression(node) && node.expression.getText(tree) === "useEffect"
    && node.arguments[0].getText(tree).includes("const pending = pendingReevaluation.current;")) finish = node.getText(tree);
  if (ts.isCallExpression(node) && node.expression.getText(tree) === "useEffect"
    && node.arguments[0].getText(tree).includes("getSceneLayerInfo(scene.id)")) layerEffect = node.getText(tree);
  ts.forEachChild(node, visit);
}
visit(tree);
const compile = source => ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const pose = {id:"a",x:200,y:200,theta:0,demSoft:"old",feasible:"可行",paretoLayer:1};
const frame={crs:"EPSG:3857",transform:[1,0,0,0,-1,0],width:1800,height:1800};
const ownership=solutionContext("scene",frame);
const edit = new SiteEdit("scene").withSolutionContext(ownership).withPoses([pose]);
const oldInputs = {...edit.searchConfig(),scene_revision:"v1"};
const inputs = {...edit.searchConfig(),scene_revision:"v2"};
const a = {...pose,evaluatedFor:evaluation.evaluationKey("scene",oldInputs,pose)};
const b = {...a,id:"b",paretoLayer:2};
const requests = [], storage = new Map();
const pending = {current:null};
const context = {...evaluation, requireSolutionContext, sceneRef:{current:{id:"scene",frame}},diversityLevel:1, setLanduseAwaitingReview() {},editRef:{current:edit.withPoses([a])},
  evaluationSnapshot:{current:{sceneId:"scene",dataVersion:{scene_revision:"v2"}}},
  diversityPool:{current:[a,b]},mergeDisplayedChoices:(pool,shown)=>[...new Map([...pool,...shown].map(p=>[p.id,p])).values()],
  evaluationInFlight:{current:new Set()},pendingReevaluation:pending,solutionGeneration:{current:{capture:()=>3}},
  createTrackedJob:async request=>{requests.push(request);return {job_id:"job"};},setNotice() {},
  setRecoveryJobId() {},window:{localStorage:{setItem:(key,value)=>storage.set(key,value)}}};
const score = runInNewContext(compile(submit)+"\nscoreWaiting",context);
await score("scene");
assert.equal(requests.length,1);
assert.equal(requests[0].plugin_id,"site.reevaluate_poses");
assert.equal(requests[0].config.expected_revision,"v2");
assert.deepEqual(Array.from(requests[0].config.poses,p=>p.id),["a","b"]);
assert.equal(storage.size,1);

for(const mode of ["success","version","generation","pose","incomplete","cancel","failure"]){
  const state = {edit:edit.withPoses([a]),notices:[],removed:0};
  const current = {...context,pendingReevaluation:{current:{...pending.current}},
    editRef:{current:state.edit},diversityPool:{current:[a,b]},
    evaluationSnapshot:{current:{sceneId:"scene",dataVersion:{scene_revision:mode==="version"?"v3":"v2"}}},
    solutionGeneration:{current:{capture:()=>mode==="generation"?4:3}},
    scene:{id:"scene"},layerInfo:{scene_id:"scene"},JobFollowUp:{isActive:()=>false},
    job:{job_id:"job",status:mode==="cancel"?"cancelled":mode==="failure"?"failed":"succeeded",
      result:{data:{coordinate_context:ownership,data_version:{scene_revision:"v2"},
        items:mode==="incomplete"?undefined:["a","b"].map(id=>({id,metrics:{dem_soft:7,is_feasible:true}}))}}},
    window:{localStorage:{removeItem(){state.removed++;}}},mergeReevaluation,
    setEdit:next=>{state.edit=next;},setNotice:message=>state.notices.push(message),useEffect:fn=>fn()};
  if(mode==="pose")current.editRef.current=edit.withPoses([{...a,x:201}]);
  for (const match of finish.matchAll(/\b(set\w+)\(/g)) if (!(match[1] in current)) current[match[1]]=()=>{};
  runInNewContext(compile(finish),current);
  if(mode==="success"){
    assert.equal(Number(state.edit.poses[0].demSoft),7);
    assert.equal(current.diversityPool.current.length,2);
    assert.equal(Number(current.diversityPool.current[1].demSoft),7);
    assert.equal(state.removed,1);
  }else{
    assert.equal(state.edit.poses[0].demSoft,"old",mode);
    assert.equal(state.removed,0,mode);
  }
}
const responses = [], received = [], cleanups = [];
const layerContext = {publicationPending:{current:null},scene:{id:"scene"},sceneReady:true,sceneVersion:1,farmlandVersion:1,
  getSceneLayerInfo:()=>new Promise(resolve=>responses.push(resolve)),setLayerInfo:value=>received.push(value),
  useEffect:fn=>cleanups.push(fn())};
for(const match of layerEffect.matchAll(/\b(set\w+)\(/g)) if(!(match[1] in layerContext))layerContext[match[1]]=()=>{};
runInNewContext(compile(layerEffect),layerContext);
cleanups[0]();
runInNewContext(compile(layerEffect),layerContext);
responses[1]({revision:"v2"});await Promise.resolve();
responses[0]({revision:"v1"});await Promise.resolve();
assert.deepEqual(received.filter(value=>value!==null),[{revision:"v2"}]);
console.log("whole-task review: hidden poses, atomic merge, cancellation and stale responses passed");
