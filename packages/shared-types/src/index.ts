import type { components } from "./openapi";

export type ApiMeta = components["schemas"]["ApiMeta"];
export type DataStatus = components["schemas"]["DataStatusData"];
export type Readiness = components["schemas"]["ReadinessData"];

export type ApiEnvelope<T> = {
  data: T;
  meta: ApiMeta;
};

export type ApiErrorEnvelope = components["schemas"]["ErrorEnvelope"];
