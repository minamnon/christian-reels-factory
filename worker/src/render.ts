export type RenderRequest = {
  topic: string;
  script: string;
  duration_seconds: number;
};

export type RenderEnvironment = {
  GITHUB_TOKEN?: string;
  GITHUB_REPOSITORY?: string;
};

export async function startRender(
  request: RenderRequest,
  secrets: RenderEnvironment
) {
  const token = secrets.GITHUB_TOKEN;
  const repository =
    secrets.GITHUB_REPOSITORY || "minamnon/christian-reels-factory";

  if (!token) {
    throw new Error("GitHub token is not configured.");
  }

  const response = await fetch(
    `https://api.github.com/repos/${repository}/actions/workflows/render-reel.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "Christian-Reels-Factory",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          topic: request.topic,
          script: request.script,
          duration_seconds: String(request.duration_seconds),
        },
      }),
    }
  );

  if (!response.ok) {
    const details = await response.text();
    throw new Error(
      `Could not start video rendering: ${response.status} ${details}`
    );
  }

  return {
    success: true,
    message: "Video rendering job submitted successfully.",
    repository,
    workflow: "render-reel.yml",
  };
}
