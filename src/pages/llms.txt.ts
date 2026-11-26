import type { APIRoute } from "astro";
import { getCollection } from "astro:content";
import { SITE } from "@consts";

// Built from the published posts and projects, so it never lists a page that does not exist
export const GET: APIRoute = async ({ site }) => {
  const base = (site?.toString() ?? "").replace(/\/$/, "");

  const posts = (await getCollection("blog"))
    .filter((post) => !post.data.draft)
    .sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());

  const projects = (await getCollection("projects"))
    .filter((project) => !project.data.draft)
    .sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());

  const lines = [
    `# ${SITE.TITLE}`,
    "",
    `> ${SITE.DESCRIPTION}`,
    "",
    "## Posts",
    "",
    ...posts.map((post) => `- [${post.data.title}](${base}/blog/${post.id}/): ${post.data.description}`),
    "",
    "## Projects",
    "",
    ...projects.map((project) => `- [${project.data.title}](${base}/projects/${project.id}/): ${project.data.description}`),
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
