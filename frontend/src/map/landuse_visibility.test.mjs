import assert from "node:assert/strict";
import {
  addLanduseDraft,
  discardLanduseDraft,
  emptyLanduseDraft,
  noteLanduseScene,
  redoLanduseDraft,
  undoLanduseDraft,
} from "../../.tmp-problem-snapshot/map/landuse_draft.js";
import { hiddenLanduseClasses } from "../../.tmp-problem-snapshot/map/toolbar_commands.js";
import {
  applyAgentLanduseVisibility,
  editingLanduseClass,
  effectiveShownClasses,
  highlightSuppressedAfterChange,
  landuseHighlightKey,
  toggleLanduseVisibility,
} from "../../.tmp-problem-snapshot/map/landuse_visibility.js";

const PAINT_TOOL = {
  field: "landuse-field",
  building: "landuse-building",
  road: "landuse-road",
  water: "landuse-water",
};

function fresh(manual = hiddenLanduseClasses()) {
  return { manual, tool: "pan", target: "field", suppressed: false };
}

function show(state) {
  const editing = editingLanduseClass(state.tool, state.target);
  const map = effectiveShownClasses(state.manual, editing, state.suppressed);
  return { editing, map, checkbox: map, tool: state.tool, manual: state.manual, suppressed: state.suppressed };
}

function select(state, tool, target = state.target) {
  const resolvedTarget = tool === "landuse-clear-class" ? target : (PAINT_TOOL[target] === tool ? target : state.target);
  const painted = Object.entries(PAINT_TOOL).find(([, name]) => name === tool)?.[0];
  const nextTarget = painted ?? resolvedTarget;
  return {
    manual: state.manual,
    tool,
    target: nextTarget,
    suppressed: highlightSuppressedAfterChange(
      state.suppressed,
      landuseHighlightKey(state.tool, state.target),
      landuseHighlightKey(tool, nextTarget),
    ),
  };
}

function toggle(state, id) {
  const next = toggleLanduseVisibility(
    state.manual,
    editingLanduseClass(state.tool, state.target),
    state.suppressed,
    id,
  );
  return { ...state, manual: next.manual, suppressed: next.suppressed };
}

{
  const idle = show(fresh());
  assert.equal(idle.editing, null);
  assert.deepEqual(idle.map, hiddenLanduseClasses());
}

{
  const building = show(select(fresh(), "landuse-clear-class", "building"));
  assert.deepEqual(building.map, { field: false, building: true, road: false, water: false });
  const water = show(select(fresh(), "landuse-clear-class", "water"));
  assert.equal(water.editing, "water");
  assert.equal(building.map.building, true);
  assert.equal(water.map.building, false);
  assert.equal(water.map.water, true);
  const field = show(select(fresh(), "landuse-clear-class", "field"));
  assert.deepEqual(field.map, { field: true, building: false, road: false, water: false });
}

{
  const painted = show(select(fresh(), "landuse-building", "building"));
  const cleared = show(select(fresh(), "landuse-clear-class", "building"));
  assert.equal(painted.editing, "building");
  assert.equal(cleared.editing, "building");
  assert.deepEqual(painted.map, cleared.map);
}

{
  const manual = { field: false, building: true, road: true, water: false };
  const shown = show(select(fresh(manual), "landuse-clear-class", "water"));
  assert.deepEqual(shown.manual, manual);
  assert.deepEqual(shown.map, { field: false, building: true, road: true, water: true });
  const left = show(select(select(fresh(manual), "landuse-clear-class", "water"), "pan"));
  assert.equal(left.editing, null);
  assert.deepEqual(left.map, manual);
  assert.equal(left.suppressed, false);
}

{
  const manual = { field: false, building: false, road: false, water: false };
  const editing = show(select(fresh(manual), "landuse-clear-class", "building"));
  assert.equal(editing.manual.building, false);
  assert.equal(editing.map.building, true);
  assert.equal(editing.checkbox.building, true);
  const left = show(select(select(fresh(manual), "landuse-clear-class", "building"), "pan"));
  assert.equal(left.map.building, false);
}

{
  const manual = { field: false, building: true, road: true, water: false };
  const reset = fresh();
  assert.deepEqual(show(reset).map, hiddenLanduseClasses());
  assert.notEqual(reset.manual, manual);
  assert.equal(reset.suppressed, false);
}

{
  const manual = { field: false, building: false, road: true, water: false };
  const afterAgent = applyAgentLanduseVisibility(false, { ...manual, water: true });
  const shown = show({ manual: afterAgent.manual, tool: "landuse-clear-class", target: "building", suppressed: afterAgent.suppressed });
  assert.equal(afterAgent.manual.building, false);
  assert.equal(afterAgent.manual.water, true);
  assert.equal(afterAgent.manual.road, true);
  assert.equal(shown.map.building, true);
  assert.equal(effectiveShownClasses(afterAgent.manual, shown.editing, false) === afterAgent.manual, false);
  assert.equal(afterAgent.manual.building, false);
}

// T1–T2: clear field auto-shows and checks; a manual close hides it and leaves the tool active.
{
  const entered = select(fresh(), "landuse-clear-class", "field");
  const visible = show(entered);
  assert.equal(visible.map.field, true);
  assert.equal(visible.checkbox.field, true);
  assert.equal(visible.manual.field, false);
  const hidden = toggle(entered, "field");
  const after = show(hidden);
  assert.equal(after.map.field, false);
  assert.equal(after.checkbox.field, false);
  assert.equal(after.tool, "landuse-clear-class");
  assert.equal(after.suppressed, true);
  assert.equal(after.editing, "field");
}

// T3: hiding the class does not block the clear-field draft.
{
  const hidden = toggle(select(fresh(), "landuse-clear-class", "field"), "field");
  const drafted = addLanduseDraft(noteLanduseScene(emptyLanduseDraft(), "scene-a"), {
    id: "field-clear-1",
    operation: "class_to_other",
    target_class_id: 1,
    points: [[0, 0], [10, 0], [10, 10]],
  });
  assert.equal(show(hidden).map.field, false);
  assert.equal(show(hidden).tool, "landuse-clear-class");
  assert.equal(drafted.dirty, true);
  assert.equal(drafted.draftItems.length, 1);
  assert.equal(drafted.draftItems[0].target_class_id, 1);
}

// T4–T5: water replaces the field highlight; returning to field shows it again.
{
  const closed = toggle(select(fresh(), "landuse-clear-class", "field"), "field");
  const water = select(closed, "landuse-clear-class", "water");
  assert.equal(water.tool, "landuse-clear-class");
  assert.equal(show(water).map.field, false);
  assert.equal(show(water).map.water, true);
  assert.equal(show(water).checkbox.water, true);
  assert.equal(water.suppressed, false);
  const back = select(water, "landuse-clear-class", "field");
  assert.equal(show(back).map.field, true);
  assert.equal(show(back).map.water, false);
  assert.equal(back.suppressed, false);
}

// T6–T7: manual building and road survive target changes and leaving the tool.
{
  const manual = { field: false, building: true, road: true, water: false };
  const water = select(fresh(manual), "landuse-clear-class", "water");
  assert.deepEqual(show(water).map, { field: false, building: true, road: true, water: true });
  const field = select(water, "landuse-clear-class", "field");
  assert.equal(show(field).map.building, true);
  assert.equal(show(field).map.road, true);
  assert.equal(show(field).map.field, true);
  const left = select(field, "pan");
  assert.deepEqual(show(left).map, manual);
  assert.equal(left.suppressed, false);
}

// T8: checking the hidden edit target shows it immediately and clears the hide.
{
  const hidden = toggle(select(fresh(), "landuse-clear-class", "field"), "field");
  const shown = toggle(hidden, "field");
  assert.equal(shown.manual.field, true);
  assert.equal(shown.suppressed, false);
  assert.equal(show(shown).map.field, true);
  assert.equal(show(shown).checkbox.field, true);
}

// T9: the same selection, a repeated read, and unrelated view changes keep the hide.
{
  const hidden = toggle(select(fresh(), "landuse-clear-class", "field"), "field");
  const reopened = select(hidden, "landuse-clear-class", "field");
  assert.equal(reopened.suppressed, true);
  assert.equal(show(reopened).map.field, false);
  const first = effectiveShownClasses(reopened.manual, "field", reopened.suppressed);
  const second = effectiveShownClasses(reopened.manual, "field", reopened.suppressed);
  assert.equal(first.field, false);
  assert.equal(second, first);
  assert.equal(highlightSuppressedAfterChange(true, "clear:field", "clear:field"), true);
}

// T10: only the clear target changes, so the tool name stays landuse-clear-class.
{
  const building = select(fresh(), "landuse-clear-class", "building");
  const water = select(building, "landuse-clear-class", "water");
  assert.equal(building.tool, "landuse-clear-class");
  assert.equal(water.tool, "landuse-clear-class");
  assert.notEqual(landuseHighlightKey(building.tool, building.target), landuseHighlightKey(water.tool, water.target));
  assert.equal(show(water).map.building, false);
  assert.equal(show(water).map.water, true);
}

// T11: paint and clear are different selections, so a hide does not carry across.
{
  let state = toggle(select(fresh(), "landuse-field"), "field");
  assert.equal(show(state).map.field, false);
  state = select(state, "landuse-clear-class", "field");
  assert.equal(state.suppressed, false);
  assert.equal(show(state).map.field, true);
  state = toggle(state, "field");
  state = select(state, "landuse-field");
  assert.equal(show(state).map.field, true);
  assert.equal(state.tool, "landuse-field");
}

// T12: leaving a scene restores the hidden default and drops the hide flag.
{
  const reset = fresh();
  assert.equal(reset.tool, "pan");
  assert.equal(reset.suppressed, false);
  assert.deepEqual(show(reset).map, hiddenLanduseClasses());
}

// T13: an agent layer write keeps the current hide, including when another class is turned on.
{
  const hidden = toggle(select(fresh(), "landuse-clear-class", "field"), "field");
  const written = applyAgentLanduseVisibility(hidden.suppressed, { ...hidden.manual, water: true, road: true });
  const next = { ...hidden, manual: written.manual, suppressed: written.suppressed };
  assert.equal(next.suppressed, true);
  assert.equal(next.manual.field, false);
  assert.equal(show(next).map.field, false);
  assert.equal(show(next).map.water, true);
  assert.equal(show(next).map.road, true);
  assert.equal(show(next).tool, "landuse-clear-class");
}

// T14: draft undo, redo, and discard do not read layer visibility.
{
  const added = addLanduseDraft(noteLanduseScene(emptyLanduseDraft(), "scene-a"), {
    id: "field-clear-1",
    operation: "class_to_other",
    target_class_id: 1,
    points: [[0, 0], [8, 0], [8, 8]],
  });
  const undone = undoLanduseDraft(added);
  const redone = redoLanduseDraft(undone);
  const dropped = discardLanduseDraft(redone);
  assert.equal(undone.draftItems.length, 0);
  assert.equal(redone.draftItems.length, 1);
  assert.equal(dropped.dirty, false);
  assert.equal(dropped.draftItems.length, 0);
  assert.equal(dropped.undo.length, 0);
}

// T15: a landuse toggle only rewrites that class. Other landuse flags stay put.
{
  const manual = { field: false, building: true, road: true, water: false };
  const hidden = toggle(select(fresh(manual), "landuse-clear-class", "water"), "water");
  assert.deepEqual(Object.keys(hidden.manual).sort(), ["building", "field", "road", "water"]);
  assert.equal(hidden.manual.building, true);
  assert.equal(hidden.manual.road, true);
  assert.equal(hidden.manual.field, false);
  assert.equal(show(hidden).map.water, false);
  assert.equal(show(hidden).map.building, true);
}
