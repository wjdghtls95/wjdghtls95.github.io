import { defineCollection, z } from "astro:content";
import { glob } from 'astro/loaders';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: "./src/content/blog" }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    date: z.coerce.date(),
    draft: z.boolean().optional(),
    tags: z.array(z.string()).optional(),
    project: z.string().optional(),
    phase: z.string().optional(),
    // 이전 프로젝트에서 같은 주제를 다룬 글이 있을 때 — 그 글에서 무엇이 발전됐는지
    evolved_from: z.array(z.object({
      project: z.string(),
      post: z.string(),
      change: z.string(),
    })).optional(),
    // 이 글의 후속작(버그 수정·방식 변경 등으로 다시 쓴 글)이 있을 때
    updated_by: z.array(z.object({
      post: z.string(),
      date: z.string().optional(),
      change: z.string(),
    })).optional(),
  }),
});

const projects = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: "./src/content/projects" }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    date: z.coerce.date(),
    draft: z.boolean().optional(),
    demoURL: z.string().optional(),
    repoURL: z.string().optional(),
    status: z.enum(["in-progress", "done", "archived"]).optional(),
    stack: z.array(z.string()).optional(),
    phases: z.array(z.object({
      id: z.string(),
      name: z.string(),
      detail: z.string().optional(),
      status: z.enum(["done", "in-progress", "todo"]),
      date: z.string().optional(),
    })).optional(),
  }),
});

export const collections = { blog, projects };
