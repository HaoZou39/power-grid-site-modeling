import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {runInNewContext} from "node:vm";
import test from "node:test";
import ts from "typescript";
import {JobFollowUp} from "../../.tmp-problem-snapshot/map/decision_run.js";
import {SiteEdit} from "../../.tmp-problem-snapshot/map/site_edit.js";
import {SolutionGeneration} from "../../.tmp-problem-snapshot/map/solution_generation.js";
import {contextFromMetadata, requireSolutionContext} from "../../.tmp-problem-snapshot/map/solution_context.js";

const source=readFileSync(new URL("./map_workspace.tsx",import.meta.url),"utf8");
const tree=ts.createSourceFile("workspace.tsx",source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const effects=[];
let deletion;
function visit(node){
  if(ts.isCallExpression(node)&&node.expression.getText(tree)==="useEffect"
    &&node.arguments[1]?.getText(tree)==="[job?.job_id, job?.status]") effects.push(node.arguments[0].getText(tree));
  if(ts.isJsxAttribute(node)&&node.name.getText(tree)==="onDeleteFarmland") deletion=node.initializer.expression.getText(tree);
  ts.forEachChild(node,visit);
}
visit(tree);
assert.ok(effects.length);
assert.ok(deletion);
const compile=body=>ts.transpileModule(body,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
const frame={crs:"EPSG:3857",transform:[1,0,0,0,-1,1000],width:1000,height:1000,frame_id:"grid"};
const owner={id:"a",title:"A",frame,ready:true};
const poses=Array.from({length:14},(_,id)=>({id:String(id),x:100+id,y:200,theta:0}));

function jobHarness(plugin="site.guided_search",delayRows=false,status="succeeded"){
  const gate=deferred();
  const rowGate=deferred();
  if(!delayRows)rowGate.resolve();
  const state={poses:[],refreshes:0,switches:0,notices:[],loads:0,alerts:[]};
  const job={job_id:"job",status:"queued",plugin_id:plugin,config:{scene_name:"a"},result:null,message:"",error:null};
  const finished={...job,status,message:status==="failed"?"Job failed":"",error:status==="failed"?{message:"场景读失败"}:null,
    result:status==="succeeded"?{data:{experiment_id:"result",scene_id:"built",data_version:{frame_id:"grid",scene_revision:"v1"}}}:null};
  const scope={job,jobRef:{current:job},jobWorkspace:{current:{id:"job",generation:0}},
    workspaceGeneration:{current:0},workspaceMounted:{current:true},solutionGeneration:{current:new SolutionGeneration()},
    JobFollowUp,followUp:{current:new JobFollowUp()},PREPARE_PLUGIN:"site.prepare_scene",BUILD_SCENE_PLUGIN:"site.build_scene",DEFAULT_SCENE:"a",
    scene:owner,sceneRef:{current:owner},editRef:{current:new SiteEdit("a",80,50)},
    evaluationSnapshot:{current:{dataVersion:{frame_id:"grid",scene_revision:"v1"}}},refining:{current:null},diversityPool:{current:[]},
    getJob:async()=>finished,getExperiments:async()=>{await gate.promise;return [{id:"result",artifacts:[{name:"data_metadata.json",url:"metadata"}]}];},
    fetchArtifactText:async()=>JSON.stringify({coordinate_context:{scene_id:"a",frame_id:"grid",frame}}),
    getScenes:async()=>{await gate.promise;return [{...owner,id:"built"}];},setScenes(){},
    contextFromMetadata,requireSolutionContext,evaluationKey:()=>"evaluation",schemeCardShouldOpen:()=>false,
    run:{current:{loadPareto:async()=>{state.loads++;await rowGate.promise;return poses;}}},
    setEdit:fn=>{scope.editRef.current=fn(scope.editRef.current);state.poses=scope.editRef.current.poses;},
    setDiversityLevel(){},setParetoLayerNote(){},setComparedIds(){},setRecommendedIds(){},setSchemeCardOpen(){},setLoadedCaseId(){},setFocusToken(){},
    setNotice:message=>state.notices.push(message),protectedFarmlandNotice:()=>null,
    completionAlert:{finish:(...args)=>{state.alerts.push(args);return true;}},
    builtSceneId:()=>"built",selectBuiltScene:(items,id)=>items.find(item=>item.id===id),
    switchScene:()=>{state.switches++;scope.workspaceGeneration.current++;},
    refreshScene:async()=>{state.refreshes++;},window:{setInterval:()=>1,clearInterval(){}},
  };
  let cleanups=[];
  function render(record){
    cleanups.forEach(cleanup=>cleanup?.());
    scope.job=record;
    scope.jobRef.current=record;
    cleanups=effects.map(body=>runInNewContext(compile(`(job=>(${body}))(job)`),scope)());
  }
  scope.setJob=record=>queueMicrotask(()=>{if(scope.job.status!==record.status)render(record);});
  return {scope,state,gate,rowGate,start:()=>render(job),finished};
}

test("terminal status cleanup does not cancel the delayed automatic pose load",async()=>{
  const h=jobHarness();h.start();await tick();
  assert.equal(h.scope.job.status,"succeeded");
  assert.equal(h.state.poses.length,0);
  h.gate.resolve();await tick();await tick();
  assert.equal(h.state.poses.length,14,JSON.stringify(h.state.notices));
  assert.equal(h.state.loads,1);
  assert.deepEqual(h.state.alerts,[["job","search","succeeded","已给出 14 个可行方案。"]]);
});

for(const status of ["failed","cancelled"]){
  test(`a ${status} guided search alerts once and does not load poses`,async()=>{
    const h=jobHarness("site.guided_search",false,status);h.start();await tick();await tick();
    assert.equal(h.state.poses.length,0);
    assert.equal(h.state.loads,0);
    assert.equal(h.state.alerts.length,1);
    assert.equal(h.state.alerts[0][0],"job");
    assert.equal(h.state.alerts[0][1],"search");
    assert.equal(h.state.alerts[0][2],status);
  });
}

test("local optimization uses the merge notice",async()=>{
  const h=jobHarness();
  h.scope.refining.current={jobId:"job"};
  h.scope.mergeRefined=()=>"局部优化完成：加入方案 2。";
  h.start();await tick();h.gate.resolve();await tick();await tick();
  assert.equal(h.state.poses.length,0);
  assert.deepEqual(h.state.alerts,[["job","refine","succeeded","局部优化完成：加入方案 2。"]]);
});

for(const plugin of ["site.prepare_scene","site.build_scene"]){
  test(`${plugin} refreshes after polling cleanup and a delayed catalog`,async()=>{
    const h=jobHarness(plugin);h.start();await tick();h.gate.resolve();await tick();await tick();
    assert.equal(h.state.refreshes+h.state.switches,1);
    assert.deepEqual(h.state.alerts,[]);
  });
}

for(const change of ["workspace","job"]){
  test(`a changed ${change} prevents the old finished task from applying`,async()=>{
    const h=jobHarness();h.start();await tick();
    if(change==="workspace")h.scope.workspaceGeneration.current++;
    else h.scope.jobRef.current={job_id:"replacement"};
    h.gate.resolve();await tick();await tick();
    assert.equal(h.state.poses.length,0);
    assert.deepEqual(h.state.alerts,[]);
  });
  test(`a changed ${change} also rejects rows arriving after metadata was accepted`,async()=>{
    const h=jobHarness("site.guided_search",true);h.start();await tick();
    h.gate.resolve();await tick();
    assert.equal(h.state.loads,1);
    if(change==="workspace")h.scope.workspaceGeneration.current++;
    else h.scope.jobRef.current={job_id:"replacement"};
    h.rowGate.resolve();await tick();
    assert.equal(h.state.poses.length,0);
  });
}

for(const plugin of ["site.prepare_scene","site.build_scene"]){
  test(`${plugin} ignores a delayed catalog after workspace navigation`,async()=>{
    const h=jobHarness(plugin);h.start();await tick();h.scope.workspaceGeneration.current++;
    h.gate.resolve();await tick();
    assert.equal(h.state.refreshes+h.state.switches,0);
  });
}

for(const error of [false,true]){
  for(const returnToA of [false,true]){
    test(`farmland delete ${error?"failure":"success"} ignores navigation ${returnToA?"A-B-A":"A-B"}`,async()=>{
      const gate=deferred(),changes=[];
      const scope={scene:owner,sceneRef:{current:owner},workspaceGeneration:{current:0},
        layerInfo:{protected_farmland:{available:true}},farmlandDeleting:true,
        deleteProtectedFarmland:()=>gate.promise,
        invalidatePublishedScene:v=>changes.push(v),setFarmlandDeleting:v=>changes.push(v),
        setFarmlandVersion:()=>changes.push("layer"),setNotice:()=>changes.push("notice")};
      runInNewContext(compile(`(${deletion})`),scope)();
      scope.workspaceGeneration.current++;
      scope.sceneRef.current={...owner,id:"b"};
      if(returnToA){scope.workspaceGeneration.current++;scope.sceneRef.current=owner;}
      if(error)gate.reject(new Error("old error"));else gate.resolve({scene_revision:"a-next"});
      await tick();
      assert.deepEqual(changes,[]);
    });
  }
}

test("farmland delete in the same workspace invalidates exactly once",async()=>{
  const revisions=[];
  const scope={scene:owner,sceneRef:{current:owner},workspaceGeneration:{current:0},
    layerInfo:{protected_farmland:{available:true}},farmlandDeleting:true,
    deleteProtectedFarmland:async()=>({scene_revision:"a-next"}),invalidatePublishedScene:v=>revisions.push(v),
    setFarmlandDeleting(){},setFarmlandVersion(){},setNotice(){}};
  runInNewContext(compile(`(${deletion})`),scope)();await tick();
  assert.deepEqual(revisions,["a-next"]);
});
