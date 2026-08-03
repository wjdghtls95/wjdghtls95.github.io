import type { Metadata, Site, Socials } from "@types";

export const SITE: Site = {
  TITLE: "Dev Archive",
  DESCRIPTION: "Notes on software engineering, AI, and building things",
  EMAIL: "wjdghtls11@gmail.com",
  NUM_POSTS_ON_HOMEPAGE: 5,
  NUM_PROJECTS_ON_HOMEPAGE: 3,
};

export const HOME: Metadata = {
  TITLE: "Home",
  DESCRIPTION: "Notes on software engineering, AI, and building things",
};

export const BLOG: Metadata = {
  TITLE: "Blog",
  DESCRIPTION: "Writing on things I've built and learned",
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
];
