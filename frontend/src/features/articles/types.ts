import type { components } from "@/shared/api/schema";

export type ArticleSource = components["schemas"]["ArticleSource"];
export type ArticleItem = components["schemas"]["StoredArticle"];
export type ArticleDetail = components["schemas"]["StoredArticleDetail"];
export type ArticlePage = components["schemas"]["StoredArticlePage"];
export type AnalysisTarget = components["schemas"]["TargetInfo"];
export type FilterRule = components["schemas"]["FilterRuleInfo"];
export type ArticleTargetLink = components["schemas"]["DecisionInfo"];
export type MaterialKind = components["schemas"]["MaterialKind"];
export type MaterialItem = components["schemas"]["StoredMaterial"];
export type MaterialDetail = components["schemas"]["StoredMaterialDetail"];
export type MaterialPage = components["schemas"]["StoredMaterialPage"];
export type TagFolder = components["schemas"]["FolderInfo"];
export type Tag = components["schemas"]["TagInfo"];
export type UnfiledTagSummary = components["schemas"]["UnfiledTagSummary"];
