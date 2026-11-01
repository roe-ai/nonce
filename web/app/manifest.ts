import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "nonce",
    short_name: "nonce",
    description: "Approve what AI apps can see in your email, calendar, files and Slack.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f6f2eb",
    theme_color: "#f6f2eb",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
