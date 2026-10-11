import type { JsonSchema } from "./api";
import { WEIGHT_KEYS, WEIGHT_PRESETS, fieldPresentation, formGroups, weightLocation } from "./config_check";

// JSON Schema remains the plugin contract; this component only translates it
// into controls and normalized values, so new plugins need no new JSX form.

export type ConfigValue =
  | string
  | number
  | boolean
  | null
  | ConfigValue[]
  | { [key: string]: ConfigValue };

export type ConfigObject = Record<string, ConfigValue>;

function hasDefault(schema: JsonSchema): boolean {
  return Object.prototype.hasOwnProperty.call(schema, "default");
}

function defaultValue(schema: JsonSchema): ConfigValue {
  if (hasDefault(schema)) return schema.default as ConfigValue;
  if (schema.type === "object") {
    return Object.fromEntries(
      Object.entries(schema.properties ?? {}).map(([key, child]) => [key, defaultValue(child)]),
    );
  }
  if (schema.type === "array") return [];
  if (schema.type === "boolean") return false;
  return "";
}

export function schemaDefaults(schema: JsonSchema): ConfigObject {
  const value = defaultValue(schema);
  return (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as ConfigObject;
}

function parseArrayValue(value: unknown, schema: JsonSchema): ConfigValue[] {
  if (Array.isArray(value)) return value as ConfigValue[];
  if (typeof value !== "string" || value.trim() === "") return [];
  if (schema.type === "string") return value.split(",").map((item) => item.trim());
  if (schema.type === "number" || schema.type === "integer") {
    return value.split(",").map((item) => {
      const parsed = Number(item.trim());
      if (!Number.isFinite(parsed) || (schema.type === "integer" && !Number.isInteger(parsed))) {
        throw new Error(`数组包含无效的${schema.type === "integer" ? "整数" : "数字"}`);
      }
      return parsed;
    });
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) throw new Error("必须是数组");
    return parsed as ConfigValue[];
  } catch (error) {
    throw new Error(`数组配置必须是逗号分隔值或 JSON 数组: ${String(error)}`);
  }
}

function normalizeValue(schema: JsonSchema, value: unknown): ConfigValue | undefined {
  if (value === undefined || value === null || value === "") {
    return schema.type === "boolean" ? false : undefined;
  }
  if (schema.type === "object") {
    const source = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as Record<string, unknown>;
    const result: ConfigObject = {};
    for (const [key, childSchema] of Object.entries(schema.properties ?? {})) {
      const child = normalizeValue(childSchema, source[key]);
      if (child !== undefined) result[key] = child;
    }
    return result;
  }
  if (schema.type === "array") {
    return parseArrayValue(value, schema.items ?? { type: "string" });
  }
  if (schema.type === "number" || schema.type === "integer") {
    const parsed = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(parsed) || (schema.type === "integer" && !Number.isInteger(parsed))) {
      throw new Error(`字段 ${schema.title ?? "数字"} 不是有效的${schema.type === "integer" ? "整数" : "数字"}`);
    }
    return parsed;
  }
  if (schema.type === "boolean") return Boolean(value);
  return String(value);
}

export function normalizeConfig(schema: JsonSchema, value: ConfigObject): Record<string, unknown> {
  return (normalizeValue(schema, value) ?? {}) as Record<string, unknown>;
}

type ConfigFieldProps = {
  name: string;
  path: string;
  schema: JsonSchema;
  value: ConfigValue | undefined;
  required: boolean;
  errors: Record<string, string>;
  onChange: (value: ConfigValue) => void;
};

function ConfigField({ name, path, schema, value, required, errors, onChange }: ConfigFieldProps) {
  const presentation = fieldPresentation(name, schema);
  const error = errors[path];
  const label = `${presentation.label}${presentation.unit ? `（${presentation.unit}）` : ""}${required ? " *" : ""}`;
  const details = (
    <>
      {presentation.hint && <small className="field-description">{presentation.hint}</small>}
      {schema.default !== undefined && <small className="field-description">默认值：{formatDefault(schema.default)}</small>}
      {error && <small className="field-error">{error}</small>}
    </>
  );

  if (schema.type === "object") {
    const objectValue = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as ConfigObject;
    return (
      <fieldset className="config-object">
        <legend>{label}</legend>
        {details}
        {Object.entries(schema.properties ?? {}).map(([childName, childSchema]) => (
          <ConfigField
            key={childName}
            name={childName}
            path={`${path}.${childName}`}
            schema={childSchema}
            value={objectValue[childName]}
            required={schema.required?.includes(childName) ?? false}
            errors={errors}
            onChange={(childValue) => onChange({ ...objectValue, [childName]: childValue })}
          />
        ))}
      </fieldset>
    );
  }

  if (schema.enum && schema.enum.length > 0) {
    return (
      <label>
        {label}
        <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
          <option value="">请选择</option>
          {schema.enum.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
        </select>
        {details}
      </label>
    );
  }

  if (schema.type === "boolean") {
    return (
      <label className="checkbox-label">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
        {label}
        {details}
      </label>
    );
  }

  if (schema.type === "array") {
    const itemType = schema.items?.type;
    const isJsonArray = itemType !== "string" && itemType !== "number" && itemType !== "integer";
    const displayValue = isJsonArray
      ? JSON.stringify(value ?? [], null, 2)
      : Array.isArray(value) ? value.join(", ") : String(value ?? "");
    return (
      <label>
        {label}
        {isJsonArray ? (
          <textarea
            value={displayValue}
            onChange={(event) => onChange(event.target.value)}
            placeholder="输入 JSON 数组"
            rows={4}
          />
        ) : (
          <input value={displayValue} onChange={(event) => onChange(event.target.value)} placeholder="用逗号分隔" />
        )}
        {details}
      </label>
    );
  }

  if (presentation.readOnly) {
    return (
      <label>
        {label}
        <input value={String(value ?? schema.default ?? "")} readOnly />
        {details}
      </label>
    );
  }

  return (
    <label>
      {label}
      <input
        type={schema.type === "number" || schema.type === "integer" ? "number" : "text"}
        step={schema.type === "integer" ? "1" : "any"}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
      />
      {details}
    </label>
  );
}

function formatDefault(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function ConfigForm({ schema, value, errors = {}, onChange }: {
  schema: JsonSchema;
  value: ConfigObject;
  errors?: Record<string, string>;
  onChange: (value: ConfigObject) => void;
}) {
  const properties = schema.properties ?? {};
  const groups = formGroups(schema);
  if (groups.length === 0) {
    return <p className="muted">此插件没有可配置参数。</p>;
  }
  const weights = weightLocation(schema);
  return (
    <div className="config-form">
      {groups.map((group) => (
        <fieldset className="config-object" key={group.id}>
          <legend>{group.title}</legend>
          {group.id === "site" && <p className="field-description">可行性规则：不可建设区域 hard count 必须为 0。</p>}
          {group.id === "preference" && weights && (
            <div className="weight-presets">
              <p className="field-description">权重总和必须为 1。所有目标当前按最小化解释。预设会写入下面的实际权重。</p>
              <div className="preset-row">
                {WEIGHT_PRESETS.map((preset) => (
                  <button key={preset.id} type="button" onClick={() => onChange(applyPreset(value, weights, preset.values))}>
                    {preset.label}
                    <small>{WEIGHT_KEYS.map((key, index) => `${key} ${preset.values[index]}`).join("，")}</small>
                  </button>
                ))}
              </div>
            </div>
          )}
          {group.names.map((name) => (
            <ConfigField
              key={name}
              name={name}
              path={name}
              schema={properties[name]}
              value={value[name]}
              required={schema.required?.includes(name) ?? false}
              errors={errors}
              onChange={(nextValue) => onChange({ ...value, [name]: nextValue })}
            />
          ))}
        </fieldset>
      ))}
    </div>
  );
}

function applyPreset(value: ConfigObject, location: "top" | "nested", weights: readonly [number, number, number]): ConfigObject {
  if (location === "nested") {
    const current = (value.objective_weights && typeof value.objective_weights === "object" && !Array.isArray(value.objective_weights)
      ? value.objective_weights
      : {}) as ConfigObject;
    return {
      ...value,
      objective_weights: {
        ...current,
        dem_soft: weights[0],
        road_distance: weights[1],
        demand_distance: weights[2],
      },
    };
  }
  return {
    ...value,
    dem_soft: weights[0],
    road_distance: weights[1],
    demand_distance: weights[2],
  };
}
