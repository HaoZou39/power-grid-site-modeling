/**
 * Schema-driven checks for a run form.
 * Domain labels are hints for known keys. Unknown plugin fields stay in the
 * algorithm group and are still rendered from the schema.
 */

export type CheckSchema = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  required?: string[];
  properties?: Record<string, CheckSchema>;
  items?: CheckSchema;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minItems?: number;
  maxItems?: number;
  "x-unit"?: string;
  "x-group"?: "identity" | "site" | "preference" | "algorithm";
  "x-readonly"?: boolean;
  $ref?: string;
  $defs?: Record<string, CheckSchema>;
  allOf?: CheckSchema[];
};

export type FieldIssue = { path: string; message: string };

export type CheckContext = {
  existingExperimentIds?: string[];
  allowOverwrite?: boolean;
  /** Named data products that are absent. Checked only for a siting schema. */
  dataMissing?: string[];
};

export const WEIGHT_KEYS = ["dem_soft", "road_distance", "demand_distance"] as const;

export const WEIGHT_PRESETS = [
  { id: "balanced", label: "均衡偏好", values: [1 / 3, 1 / 3, 1 / 3] },
  { id: "terrain", label: "偏地形", values: [1, 0, 0] },
  { id: "road", label: "偏道路", values: [0, 1, 0] },
  { id: "demand", label: "偏需求点", values: [0, 0, 1] },
] as const;

const GROUP_ORDER = ["identity", "site", "preference", "algorithm"] as const;
export type FormGroupId = (typeof GROUP_ORDER)[number];

const GROUP_TITLE: Record<FormGroupId, string> = {
  identity: "数据与实验身份",
  site: "站点和约束",
  preference: "目标偏好",
  algorithm: "算法和运行参数",
};

const DOMAIN_FIELDS: Record<string, { group: FormGroupId; label: string; unit?: string; hint?: string; readOnly?: boolean }> = {
  experiment_name: { group: "identity", label: "实验名称", hint: "用作本次运行的名称。输出目录由后端决定时，不需要手写路径。" },
  seed: { group: "identity", label: "随机 seed", hint: "相同 seed 用于复现需求点和算法中的随机选择。" },
  rect_w_m: { group: "site", label: "建筑矩形宽度", unit: "m" },
  rect_h_m: { group: "site", label: "建筑矩形高度", unit: "m" },
  demand_on_buildable_only: { group: "site", label: "只在可建设区域生成需求点" },
  target_resolution_m: { group: "site", label: "分辨率", unit: "m", readOnly: true, hint: "分辨率来自已经生成的数据网格，不能在这里修改。" },
  resolution_m: { group: "site", label: "分辨率", unit: "m", readOnly: true, hint: "分辨率来自已经生成的数据网格，不能在这里修改。" },
  dem_soft: { group: "preference", label: "地形平整度权重" },
  road_distance: { group: "preference", label: "道路距离权重" },
  demand_distance: { group: "preference", label: "需求点距离权重" },
  objective_weights: { group: "preference", label: "目标权重", hint: "权重总和必须为 1。所有目标当前按最小化解释。" },
};

export type FieldPresentation = {
  group: FormGroupId;
  label: string;
  unit?: string;
  hint?: string;
  readOnly: boolean;
};

export type FormGroup = { id: FormGroupId; title: string; names: string[] };

/** Inline local JSON Schema $ref and allOf so nested plugin models stay visible to the form. */
export function resolveSchemaRefs(schema: CheckSchema, root?: CheckSchema): CheckSchema {
  const base = root ?? schema;
  let current = schema;
  if (current.$ref) {
    const name = current.$ref.slice(current.$ref.lastIndexOf("/") + 1);
    const target = base.$defs?.[name];
    if (target) {
      const { $ref: _ignored, ...rest } = current;
      current = { ...resolveSchemaRefs(target, base), ...rest };
    }
  }
  if (current.allOf) {
    const merged = current.allOf.reduce<CheckSchema>(
      (accumulator, item) => ({ ...accumulator, ...resolveSchemaRefs(item, base) }),
      {},
    );
    const { allOf: _ignored, ...rest } = current;
    current = { ...merged, ...rest };
  }
  if (current.properties) {
    current = {
      ...current,
      properties: Object.fromEntries(
        Object.entries(current.properties).map(([key, child]) => [key, resolveSchemaRefs(child, base)]),
      ),
    };
  }
  if (current.items) current = { ...current, items: resolveSchemaRefs(current.items, base) };
  return current;
}

export function hasSitingFields(schema: CheckSchema): boolean {
  const names = Object.keys(schema.properties ?? {});
  return names.some((name) => name === "rect_w_m" || name === "objective_weights" || WEIGHT_KEYS.includes(name as (typeof WEIGHT_KEYS)[number]));
}

export function fieldPresentation(name: string, schema: CheckSchema): FieldPresentation {
  const domain = DOMAIN_FIELDS[name];
  const group = schema["x-group"] ?? domain?.group ?? "algorithm";
  return {
    group,
    label: schema.title || domain?.label || name,
    unit: schema["x-unit"] ?? domain?.unit,
    hint: schema.description || domain?.hint,
    readOnly: schema["x-readonly"] === true || domain?.readOnly === true,
  };
}

export function formGroups(schema: CheckSchema): FormGroup[] {
  const buckets = new Map<FormGroupId, string[]>(GROUP_ORDER.map((id) => [id, []]));
  for (const name of Object.keys(schema.properties ?? {})) {
    const group = fieldPresentation(name, schema.properties?.[name] ?? {}).group;
    buckets.get(group)?.push(name);
  }
  return GROUP_ORDER
    .map((id) => ({ id, title: GROUP_TITLE[id], names: buckets.get(id) ?? [] }))
    .filter((group) => group.names.length > 0);
}

export function weightLocation(schema: CheckSchema): "top" | "nested" | null {
  const properties = schema.properties ?? {};
  if (WEIGHT_KEYS.every((key) => isNumberSchema(properties[key]))) return "top";
  const nested = properties.objective_weights?.properties;
  if (nested && WEIGHT_KEYS.every((key) => isNumberSchema(nested[key]))) return "nested";
  return null;
}

export function checkConfig(schema: CheckSchema, value: Record<string, unknown>, context: CheckContext = {}): FieldIssue[] {
  const issues: FieldIssue[] = [];
  walk(schema, value, "", true, issues);
  checkWeightSum(schema, value, issues);
  const experimentName = value.experiment_name;
  if (
    typeof experimentName === "string"
    && experimentName.trim()
    && context.existingExperimentIds?.includes(experimentName)
    && !context.allowOverwrite
  ) {
    issues.push({ path: "experiment_name", message: "该实验名称已有结果。确认覆盖后才能运行。" });
  }
  if (hasSitingFields(schema) && context.dataMissing && context.dataMissing.length > 0) {
    issues.push({ path: "", message: `数据产物尚未准备好：${context.dataMissing.join("、")}` });
  }
  return issues;
}

function walk(schema: CheckSchema, value: unknown, path: string, required: boolean, issues: FieldIssue[]): void {
  if (schema.properties) {
    const source = asRecord(value) ?? {};
    const requiredNames = new Set(schema.required ?? []);
    for (const [key, child] of Object.entries(schema.properties)) {
      const childPath = path ? `${path}.${key}` : key;
      walk(child, source[key], childPath, requiredNames.has(key), issues);
    }
    return;
  }
  if (schema.type === "array") {
    const items = arrayItems(value, schema.items);
    if (items === null) {
      issues.push({ path, message: "请输入有效的列表" });
      return;
    }
    if (schema.minItems !== undefined && items.length < schema.minItems) {
      issues.push({ path, message: `至少需要 ${schema.minItems} 项` });
    }
    if (schema.maxItems !== undefined && items.length > schema.maxItems) {
      issues.push({ path, message: `最多 ${schema.maxItems} 项` });
    }
    return;
  }
  if (schema.type === "number" || schema.type === "integer") {
    if (isBlank(value)) {
      if (required) issues.push({ path, message: `请填写${schema.title ?? path}` });
      return;
    }
    const parsed = finiteNumber(value);
    if (parsed === null) {
      issues.push({ path, message: schema.type === "integer" ? "请输入整数" : "请输入有限数字" });
      return;
    }
    if (schema.type === "integer" && !Number.isInteger(parsed)) {
      issues.push({ path, message: "请输入整数" });
      return;
    }
    if (schema.minimum !== undefined && parsed < schema.minimum) {
      issues.push({ path, message: `不能小于 ${schema.minimum}` });
    }
    if (schema.exclusiveMinimum !== undefined && parsed <= schema.exclusiveMinimum) {
      issues.push({ path, message: `必须大于 ${schema.exclusiveMinimum}` });
    }
    if (schema.maximum !== undefined && parsed > schema.maximum) {
      issues.push({ path, message: `不能大于 ${schema.maximum}` });
    }
    if (schema.exclusiveMaximum !== undefined && parsed >= schema.exclusiveMaximum) {
      issues.push({ path, message: `必须小于 ${schema.exclusiveMaximum}` });
    }
    return;
  }
  if (schema.type === "boolean") return;
  if (required && isBlank(value)) issues.push({ path, message: `请填写${schema.title ?? path}` });
}

function checkWeightSum(schema: CheckSchema, value: Record<string, unknown>, issues: FieldIssue[]): void {
  const location = weightLocation(schema);
  if (!location) return;
  const source = location === "top"
    ? value
    : asRecord(value.objective_weights) ?? {};
  const weights = WEIGHT_KEYS.map((key) => finiteNumber(source[key]));
  if (weights.some((item) => item === null)) return;
  const sum = (weights as number[]).reduce((total, item) => total + item, 0);
  if (Math.abs(sum - 1) > 1e-6) {
    const path = location === "top" ? WEIGHT_KEYS[0] : "objective_weights";
    issues.push({ path, message: `权重总和必须为 1，当前为 ${sum}` });
  }
}

function arrayItems(value: unknown, itemSchema: CheckSchema | undefined): unknown[] | null {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return isBlank(value) ? [] : null;
  if (value.trim() === "") return [];
  const itemType = itemSchema?.type;
  if (itemType === "number" || itemType === "integer") {
    const numbers = value.split(",").map((item) => finiteNumber(item.trim()));
    if (numbers.some((item) => item === null)) return null;
    return numbers;
  }
  return value.split(",").map((item) => item.trim()).filter((item) => item.length > 0);
}

function isNumberSchema(schema: CheckSchema | undefined): boolean {
  return schema?.type === "number" || schema?.type === "integer";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function isBlank(value: unknown): boolean {
  return value === undefined || value === null || value === "";
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
