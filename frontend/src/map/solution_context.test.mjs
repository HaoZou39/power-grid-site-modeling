import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {runInNewContext} from "node:vm";
import ts from "typescript";
import {activateSiteFrame, siteFrameFromInfo} from "../../.tmp-problem-snapshot/map/site_frame.js";
import {solutionContext, contextFromMetadata, requireSolutionContext} from "../../.tmp-problem-snapshot/map/solution_context.js";
import {SiteEdit} from "../../.tmp-problem-snapshot/map/site_edit.js";
import {exportSolutionsCsv, exportSolutionsJson} from "../../.tmp-problem-snapshot/map/solution_export.js";
import {readReevaluation, restoreReevaluation} from "../../.tmp-problem-snapshot/map/reevaluation_recovery.js";
import {GuidedDecisionRun} from "../../.tmp-problem-snapshot/map/decision_run.js";
const a = {crs:"EPSG:32651",transform:[1,0,253000,0,-1,3100000],width:8000,height:8000,frame_id:"frame-a"};
const b = {...a,transform:[1,0,253400,0,-1,3100400],frame_id:"frame-b"};
const context = solutionContext("a",a);
const point = {id:"p",x:1727.461669921875,y:4874.951171875,theta:.6,demSoft:"1",roadDistance:"",demandDistance:"",
  roadHaul:"",offroadHaul:"",haulRise:"",obstacleHardCount:"",feasible:"可行"};
const expected = siteFrameFromInfo(a);
activateSiteFrame(b);
const exported = JSON.parse(exportSolutionsJson(context,124.5,69,[point]));
assert.equal(exported.solutions[0].longitude_deg,Number(expected.localToLngLat(point).lng.toFixed(6)));
assert.equal(exported.solutions[0].azimuth_deg,Number(expected.widthBearing(point.theta,point).toFixed(3)));
assert.ok(exportSolutionsCsv(context,[point]).includes(expected.localToLngLat(point).lat.toFixed(6)));
assert.throws(()=>requireSolutionContext(context,"b",b),/不一致/);
assert.throws(()=>requireSolutionContext(context,"a",b),/不一致/);
assert.throws(()=>contextFromMetadata("a",{}),/缺少/);
assert.throws(()=>requireSolutionContext(null,"a"),/缺少/);
assert.equal(contextFromMetadata("a",{dem:{reference_crs:a.crs,target_transform:a.transform,shape:[8000,8000]}}).frame.width,8000);
assert.equal(contextFromMetadata("a",{frame:a}).frame.frame_id,a.frame_id);
assert.equal(contextFromMetadata("a",{frame:a,dem:{reference_crs:"bad"}}).frame.width,8000);
let stillCurrent = true, reads = 0;
const run = new GuidedDecisionRun({
  getExperiments: async () => [{id:"case",artifacts:[
    {name:"data_metadata.json",url:"metadata"}, {name:"workspace_solutions.json",url:"solutions"},
  ]}],
  fetchArtifactText: async (url) => {
    if (url === "metadata") return JSON.stringify({coordinate_context:context});
    reads++;
    return JSON.stringify({format:"workspace-solutions-v1",solutions:[{...point,manual:true,pareto_layer:1}]});
  },
});
await assert.rejects(run.loadBoundSolutions("case","a",b,true,()=>stillCurrent),/不一致/);
assert.equal(reads,0);
const bound = await run.loadBoundSolutions("case","a",a,true,()=>stillCurrent);
assert.equal(bound.context.frame_id,"frame-a");
assert.equal(bound.pool[0].id,"p");
const interrupted = run.loadBoundSolutions("case","a",a,true,()=>stillCurrent);
stillCurrent = false;
assert.equal(await interrupted,null);
assert.equal(reads,1);
const edit=new SiteEdit("a",124.5,69).withSolutionContext(context).withPoses([point]);
const switched=edit.withScene("b");
assert.equal(switched.poses.length,0);
assert.equal(switched.solutionContext,null);
activateSiteFrame(a);
const inputs={...edit.withPolicies("blocked","blocked",.5).withRoadSetback(9).searchConfig(),scene_revision:"v2",origin_x:300,origin_y:400};
const saved={format:2,jobId:"job",sceneId:"a",context,inputs,poses:[point,{...point,id:"hidden",paretoLayer:2}],diversityLevel:2,selectedId:"hidden",generation:0};
const restored=restoreReevaluation(readReevaluation(JSON.stringify(saved)));
assert.equal(restored.widthM,124.5);
assert.equal(restored.heightM,69);
assert.equal(restored.roadSetbackM,9);
assert.equal(restored.fieldPolicy,"blocked");
assert.equal(restored.searchConfig().include_demand,false);
assert.equal(restored.searchConfig().field_cost,.5);
assert.equal(restored.selectedPoseId,"hidden");
assert.deepEqual(restored.origin,{x:300,y:400});
assert.equal(restored.poses.length,2);
assert.throws(()=>readReevaluation(JSON.stringify({...saved,context:null})),/缺少/);
for (const retired of [{field_policy:"costly",field_cost:.7},{include_demand:true},{field_cost:.35}]) {
  const legacy={...saved,inputs:{...inputs,...retired}};
  const raw=JSON.stringify(legacy);
  assert.throws(()=>readReevaluation(raw),/原记录已保留/);
  assert.throws(()=>restoreReevaluation(legacy),/原记录已保留/);
  assert.equal(JSON.stringify(legacy),raw,"legacy task inputs and poses must stay intact");
}
// Execute the actual refresh handler with an out-of-order catalog response.
const source = readFileSync(new URL("./map_workspace.tsx",import.meta.url),"utf8");
const tree = ts.createSourceFile("workspace.tsx",source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const handlers = new Map();
function visit(n){if(ts.isFunctionDeclaration(n)&&n.name)handlers.set(n.name.text,n.getText(tree));ts.forEachChild(n,visit);}
visit(tree);
let resolveScenes;
const navigation={current:0},owner={current:{id:"a",frame:a}},edits={current:edit};
const state={switches:0,scene:owner.current};
const scope={workspaceGeneration:navigation,sceneRef:owner,editRef:edits,DEFAULT_SCENE:"a",
  getScenes:()=>new Promise(resolve=>resolveScenes=resolve),setScenes(){},setSceneFrame(){},setSceneVersion(){},
  initialEdit:{current:null},setEdit:next=>{edits.current=next;},setScene:next=>{state.scene=next;},
  activateSiteFrame,switchScene:()=>{state.switches++;}};
const js=ts.transpileModule(handlers.get("refreshScene"),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const refresh=runInNewContext(js+"\nrefreshScene",scope);
const delayed=refresh("b");navigation.current++;
resolveScenes([{id:"a",frame:a},{id:"b",frame:b}]);await delayed;
assert.equal(state.switches,0);
assert.equal(state.scene.id,"a");
assert.equal(edits.current.poses.length,1);
const realSwitch=refresh("b");resolveScenes([{id:"b",frame:b}]);await realSwitch;
assert.equal(state.switches,1,"a fresh scene change must use the unified reset path");
// Publishing a landuse-only draft confirms its version before the explicit job.
const publication={current:null}, snapshot={current:{}}, revision={current:null};
let created=0;
const publishScope={publicationPending:publication,
  solutionGeneration:{current:{advance(){}}},reportController:{current:null},
  layerInfoRef:{current:{scene_id:"a",roads:{road_product_id:"roads"},protected_farmland:{content_sha256:"farm"},data_version:{frame_id:"frame-a",scene_revision:"v1"}}},
  evaluationSnapshot:snapshot,sceneRevisionOverride:revision,workspaceGeneration:{current:0},
  editRef:{current:edit},diversityPool:{current:[]},mergeDisplayedChoices:()=>[],
  setPublicationBlocked(){},setReport(){},setLanduseAwaitingReview(){},setSceneVersion(){},setLayerInfo(){},
  jobStartingRef:{current:false},setJobStarting(){},setSubmittingShownJob(){},jobWorkspace:{current:null},jobRef:{current:null},setJob(){},
  BUILD_SCENE_PLUGIN:"build",GuidedDecisionRun:{pluginId:"site.guided_search"},setSiteOutcome(){},createJob:async()=>{created++;return {job_id:"explicit"};}};
const publishJs=ts.transpileModule(["invalidatePublishedScene","rememberPublishedRevision","createTrackedJob"].map(name=>handlers.get(name)).join("\n"),
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const publish=runInNewContext(publishJs+"\n({rememberPublishedRevision,createTrackedJob,invalidatePublishedScene})",publishScope);
publish.rememberPublishedRevision("a","v2");
assert.equal(snapshot.current.dataVersion.scene_revision,"v2");
assert.equal(publication.current,null,"a confirmed landuse revision must allow the requested computation");
await publish.createTrackedJob({plugin_id:"site.guided_search"});
assert.equal(created,1);
publish.invalidatePublishedScene("v3");
await assert.rejects(()=>publish.createTrackedJob({plugin_id:"site.guided_search"}),/版本尚未确认/);
assert.equal(created,1,"an unconfirmed publication must continue to block jobs");
console.log("coordinate ownership, bound export and non-default recovery passed");
