import type { Metadata, Site, Socials } from "@types";

export const SITE: Site = {
  TITLE: "정호의 블로그",
  DESCRIPTION: "개발, AI, 사이드프로젝트에 대한 기록",
  EMAIL: "lionjh95@gmail.com",
  NUM_POSTS_ON_HOMEPAGE: 5,
  NUM_PROJECTS_ON_HOMEPAGE: 3,
};

export const HOME: Metadata = {
  TITLE: "Home",
  DESCRIPTION: "개발, AI, 사이드프로젝트에 대한 기록",
};

export const BLOG: Metadata = {
  TITLE: "Blog",
  DESCRIPTION: "개발하면서 정리한 글들",
};

export const PROJECTS: Metadata = {
  TITLE: "Projects",
  DESCRIPTION: "만들고 있는 것들",
};

export const SOCIALS: Socials = [
  {
    NAME: "GitHub",
    HREF: "https://github.com/wjdghtls95",
  },
  {
    NAME: "Email",
    HREF: "mailto:lionjh95@gmail.com",
  },
];
