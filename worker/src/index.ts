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
  constructor(
    message: string,
    public status?: number
  ) {
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
- ممنوع إظهار التفكير الداخلي أو خطوات التحليل أو أي كلام عن طريقة عملك.
- لا تستخدم جداول.
- لا تكتب مقدمات أو اعتذارات.
- استخدم لهجة مصرية سليمة وطبيعية.
- اجعل السيناريو مناسبًا فعلًا للمدة المطلوبة.
- قسّم الفيديو إلى مشاهد بتوقيت واضح.
- اجعل أول 3 ثوانٍ جذابة وقوية.
- لا تخترع آيات أو اقتباسات كتابية.
- لا تضع نص آية بين علامتي اقتباس إلا إذا كنت متأكدًا من دقته.
- اذكر المرجع الكتابي بوضوح، واطلب مراجعة نص الآية من ترجمة معتمدة عند الحاجة.
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
    \`https://generativelanguage.googleapis.com/v1beta/models/\${GEMINI_MODEL}:generateContent\`,
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
        Authorization: \`Bearer \${apiKey}\`,
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

function createServer() {
  const server = new McpServer({
    name: "christian-reels-factory",
    version: "0.4.0",
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
        provider: z.enum(["auto", "gemini", "groq"]).optional()
          .describe("auto uses Gemini then Groq fallback; gemini or groq tests a provider directly."),
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
              \`CHRISTIAN REEL - GENERATED BY \${result.provider.toUpperCase()}\n\n\${result.text}\`,
          }],
        };
      } catch (error) {
        return {
          content: [{
            type: "text",
            text: \`فشل توليد السيناريو: \${
              error instanceof Error ? error.message : "Unknown error"
            }\`,
          }],
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
