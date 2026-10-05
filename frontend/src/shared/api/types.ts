import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type Project = Schemas["ProjectOut"];
export type UserOut = Schemas["UserOut"];
export type RoleOut = Schemas["RoleOut"];
export type Source = Schemas["SourceOut"];
export type ConnectorType = Schemas["ConnectorType"];
export type CatalogTable = Schemas["TableOut"];
export type CatalogColumn = Schemas["ColumnOut"];
export type RunResult = Schemas["RunOut"];
export type SavedQuery = Schemas["SavedQueryOut"];
