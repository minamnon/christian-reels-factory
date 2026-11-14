import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { env } from "cloudflare:workers";
import { z } from "zod";

const GEMINI_MODEL = "gemini-3.8-flash";
const GROQ_MODEL = "openai/gpt-oss-120b";

type Provider = "auto" | "gemini" | "groq";

type GenerationResult = {
  text: string;
  provider: string;
};

class ProviderError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
    this.name = "ProviderError";
  }
}

function buildPrompt(
  topic: string,
  bibleReference?: string,
  keyMessage?: string,
  duration = 35
) {
  return `
أنت كاتب سيناريوهات محترف متخصص في Reels مسيحية لصفحة "الكتاب المقدس مسموع ومقروء".

المطلوب:
إنشاء سيناريو مسيحي أصلي ومؤثر باللهجة المصرية الطبيعية.

الموضوع: ${topic}
المدة: ${duration} ثانية
المرجع الكتابي: ${bibleReference || "اختر مرجعًا مناسبًا دون اختلاق نص آية"}
الرسالة الأساسية: ${keyMessage || "اختر رسالة روحية مناسبة"}

قواعد صارمة:
- أخرج الإجابة النهائية فقط.
- ممنوع إظهار التفكير الداخلي أو خطوات التحليل.
- لا تستخدم جداول.
- استخدم لهجة مصرية سليمة وطبيعية.
- اجعل أول 3 ثوانٍ جذابة وقوية.
- لا تخترع آيات أو اقتباسات كتابية.
- اذكر المرجع الكتابي بوضوح.
- اختم برسالة روحية مؤثرة.

التنسيق:
عنوان الريل:
Hook:
المشهد الأول:
المشهد الثاني:
المشهد الثالث:
الرسالة الختامية:
المرجع الكتابي:
وصف المنشور:
الهاشتاجات:

اكتب نصًا متماسكًا وجاهزًا للتسجيل الصوتي.
`;
}

async function generateWithGemini(
  prompt: string,
  apiKey: string
): Promise<GenerationResult> {
  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": apiKey,
      },
      body: JSON.stringify({
        contents: [{
          role: "user",
          parts: [{ text: prompt }],
        }],
        generationConfig: {
          temperature: 0.75,
          maxOutputTokens: 1800,
        },
      }),
    }
  );

  const data: any = await response.json();

  if (!response.ok) {
    throw new ProviderError(
      data?.error?.message || "Gemini API error",
      response.status
    );
  }

  const text = data?.candidates?.[0]?.content?.parts
    ?.map((part: any) => part.text || "")
    .join("")
    .trim();

  if (!text) {
    throw new ProviderError("Gemini returned an empty response.");
  }

  return { text, provider: "Gemini" };
}

async function generateWithGroq(
  prompt: string,
  apiKey: string
): Promise<GenerationResult> {
  const response = await fetch(
    "https://api.groq.com/openai/v1/chat/completions",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: GROQ_MODEL,
        messages: [
          {
            role: "system",
            content:
              "أنت كاتب سيناريوهات محترف. أخرج النص النهائي فقط. لا تعرض التفكير الداخلي أو التحليل أو الملاحظات. اكتب عربية مصرية سليمة.",
          },
          {
            role: "user",
            content: prompt,
          },
        ],
        temperature: 0.7,
        max_completion_tokens: 1600,
      }),
    }
  );

  const data: any = await response.json();

  if (!response.ok) {
    throw new ProviderError(
      data?.error?.message || "Groq API error",
      response.status
    );
  }

  const text = data?.choices?.[0]?.message?.content?.trim();

  if (!text) {
    throw new ProviderError("Groq returned an empty response.");
  }

  return { text, provider: "Groq" };
}

function canFallback(error: unknown): boolean {
  if (!(error instanceof ProviderError)) {
    return true;
  }

  return [408, 429, 500, 502, 503, 504].includes(
    error.status ?? 0
  );
}

// ---------------------------------------------------------
// GitHub helpers
// ---------------------------------------------------------

function getGithubConfig() {
  const secrets = env as unknown as {
    GITHUB_TOKEN?: string;
    GITHUB_REPOSITORY?: string;
  };

  const token = secrets.GITHUB_TOKEN;
  const repository =
    secrets.GITHUB_REPOSITORY || "minamnon/christian-reels-factory";

  if (!token) {
    throw new Error(
      "GITHUB_TOKEN is not configured in Cloudflare Worker secrets."
    );
  }

  return { token, repository };
}

function githubHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
    "User-Agent": "Christian-Reels-Factory",
  };
}

async function githubGet(path: string, token: string): Promise<any> {
  const response = await fetch(`https://api.github.com${path}`, {
    method: "GET",
    headers: githubHeaders(token),
  });

  if (!response.ok) {
    const details = (await response.text()).slice(0, 500);
    const hint =
      [401, 403, 404].includes(response.status)
        ? " (check GITHUB_TOKEN permissions: Actions read/write)"
        : "";
    throw new Error(
      `GitHub API error ${response.status}${hint}: ${details}`
    );
  }

  return response.json();
}

function createServer() {
  const server = new McpServer({
    name: "christian-reels-factory",
    version: "0.6.0",
  });

  server.registerTool(
    "project_status",
    {
      description: "Check the project status.",
    },
    async () => ({
      content: [{
        type: "text",
        text: "Christian Reels Factory MCP server is running. Gemini primary, Groq fallback.",
      }],
    })
  );

  server.registerTool(
    "generate_script",
    {
      description:
        "Generate an original Arabic Christian Reel script using Gemini with automatic Groq fallback.",
      inputSchema: z.object({
        topic: z.string().min(3).describe("Reel topic"),
        bible_reference: z.string().optional(),
        key_message: z.string().optional(),
        duration_seconds: z.number().int().min(20).max(60).optional(),
        provider: z.enum(["auto", "gemini", "groq"]).optional(),
      }),
    },
    async ({
      topic,
      bible_reference,
      key_message,
      duration_seconds,
      provider,
    }) => {
      const secrets = env as unknown as {
        GEMINI_API_KEY?: string;
        GROQ_API_KEY?: string;
      };

      const geminiKey = secrets.GEMINI_API_KEY;
      const groqKey = secrets.GROQ_API_KEY;

      const selectedProvider: Provider = provider ?? "auto";
      const prompt = buildPrompt(
        topic,
        bible_reference,
        key_message,
        duration_seconds ?? 35
      );

      try {
        let result: GenerationResult;

        if (selectedProvider === "gemini") {
          if (!geminiKey) {
            throw new Error("مفتاح Gemini غير موجود في Cloudflare Secrets.");
          }
          result = await generateWithGemini(prompt, geminiKey);
        } else if (selectedProvider === "groq") {
          if (!groqKey) {
            throw new Error("مفتاح Groq غير موجود في Cloudflare Secrets.");
          }
          result = await generateWithGroq(prompt, groqKey);
        } else {
          if (geminiKey) {
            try {
              result = await generateWithGemini(prompt, geminiKey);
            } catch (error) {
              if (!canFallback(error)) {
                throw error;
              }

              if (!groqKey) {
                throw new Error(
                  "تعذر استخدام Gemini، ومفتاح Groq غير موجود."
                );
              }

              result = await generateWithGroq(prompt, groqKey);
              result.provider = "Groq (automatic fallback)";
            }
          } else if (groqKey) {
            result = await generateWithGroq(prompt, groqKey);
          } else {
            throw new Error(
              "لا يوجد مفتاح Gemini أو Groq في Cloudflare Secrets."
            );
          }
        }

        return {
          content: [{
            type: "text",
            text:
              `CHRISTIAN REEL - GENERATED BY ${result.provider.toUpperCase()}\n\n${result.text}`,
          }],
        };
      } catch (error) {
        return {
          content: [{
            type: "text",
            text: `فشل توليد السيناريو: ${
              error instanceof Error ? error.message : "Unknown error"
            }`,
          }],
        };
      }
    }
  );

  // Automatic video rendering tool
  server.registerTool(
    "render_reel",
    {
      description:
        "Start rendering a complete Christian Reel MP4 from its Arabic script using GitHub Actions. Returns the GitHub run ID; use render_status to follow progress.",
      inputSchema: z.object({
        topic: z.string().min(3).max(120),
        script: z.string().min(30).max(10000),
        duration_seconds: z.number().int().min(20).max(60).default(35),
      }),
    },
    async ({ topic, script, duration_seconds }) => {
      try {
        const { token, repository } = getGithubConfig();

        const response = await fetch(
          `https://api.github.com/repos/${repository}/actions/workflows/render-reel.yml/dispatches`,
          {
            method: "POST",
            headers: githubHeaders(token),
            body: JSON.stringify({
              ref: "main",
              inputs: {
                topic,
                script,
                duration_seconds: String(duration_seconds),
              },
              return_run_details: true,
            }),
          }
        );

        if (!response.ok) {
          const details = (await response.text()).slice(0, 500);
          throw new Error(
            `GitHub Actions error ${response.status}: ${details}`
          );
        }

        let runId: number | undefined;
        let runUrl: string | undefined;

        if (response.status === 200) {
          try {
            const data: any = await response.json();
            runId = data?.workflow_run_id ?? data?.id;
            runUrl = data?.html_url;
          } catch {
            // Body could not be parsed; the run ID stays unknown.
          }
        }

        const lines = [
          "RENDER_JOB_SUBMITTED",
          `Repository: ${repository}`,
          "Workflow: render-reel.yml",
          runId
            ? `Run ID: ${runId}`
            : "Run ID: not returned by GitHub",
        ];

        if (runUrl) {
          lines.push(`Run URL: ${runUrl}`);
        }

        lines.push(
          runId
            ? "The MP4 is not ready yet. Use render_status with this run_id to check progress."
            : "The MP4 is not ready yet. The run ID could not be determined."
        );

        return {
          content: [{ type: "text", text: lines.join("\n") }],
        };
      } catch (error) {
        return {
          content: [{
            type: "text",
            text: `فشل بدء إنتاج الفيديو: ${
              error instanceof Error ? error.message : "Unknown error"
            }`,
          }],
          isError: true,
        };
      }
    }
  );

  // Render status tool
  server.registerTool(
    "render_status",
    {
      description:
        "Check the status of a render job started by render_reel, using its GitHub run ID. On failure it names the failed step; on success it lists the output artifact.",
      inputSchema: z.object({
        run_id: z.number().int().positive(),
      }),
    },
    async ({ run_id }) => {
      try {
        const { token, repository } = getGithubConfig();

        const run: any = await githubGet(
          `/repos/${repository}/actions/runs/${run_id}`,
          token
        );

        const lines = [
          `RUN_STATUS: ${run.status}`,
          `Conclusion: ${run.conclusion ?? "none yet"}`,
          `Run URL: ${run.html_url}`,
        ];

        if (run.status === "completed") {
          if (run.conclusion === "success") {
            const artifactData: any = await githubGet(
              `/repos/${repository}/actions/runs/${run_id}/artifacts`,
              token
            );
            const artifacts: any[] = artifactData?.artifacts ?? [];

            if (artifacts.length === 0) {
              lines.push("No artifacts were found for this run.");
            } else {
              for (const artifact of artifacts) {
                lines.push(
                  `Artifact: ${artifact.name} | ${artifact.size_in_bytes} bytes | expired: ${artifact.expired}`
                );
              }
              try {
                const release: any = await githubGet(
                  `/repos/${repository}/releases/tags/reel-${run_id}`,
                  token
                );
                const mp4 = (release?.assets ?? []).find((a: any) =>
                  String(a.name).toLowerCase().endsWith(".mp4")
                );
                if (mp4) {
                  lines.push(`Download URL: ${mp4.browser_download_url}`);
                  lines.push(`Release URL: ${release.html_url}`);
                } else {
                  lines.push("Release found but it has no MP4 asset.");
                }
              } catch {
                lines.push(
                  `No release found for tag reel-${run_id}. Use the Artifact from the Run URL.`
                );
              }
            }
          } else {
            const jobData: any = await githubGet(
              `/repos/${repository}/actions/runs/${run_id}/jobs`,
              token
            );
            const failedSteps: string[] = [];

            for (const job of jobData?.jobs ?? []) {
              for (const step of job.steps ?? []) {
                if (step.conclusion === "failure") {
                  failedSteps.push(`${job.name} -> ${step.name}`);
                }
              }
            }

            if (failedSteps.length > 0) {
              lines.push("Failed step(s): " + failedSteps.join("; "));
            } else {
              lines.push("No failed step was identified.");
            }
          }
        }

        return {
          content: [{ type: "text", text: lines.join("\n") }],
        };
      } catch (error) {
        return {
          content: [{
            type: "text",
            text: `فشل جلب حالة التشغيل: ${
              error instanceof Error ? error.message : "Unknown error"
            }`,
          }],
          isError: true,
        };
      }
    }
  );

  return server;
}

const handler = createMcpHandler(createServer);

export default {
  fetch(request, env, ctx) {
    return handler(request, env, ctx);
  },
} satisfies ExportedHandler;
