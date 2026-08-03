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
