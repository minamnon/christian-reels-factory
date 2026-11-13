
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { env } from "cloudflare:workers";
import { z } from "zod";

const MODEL = "gemini-3.8-flash";

function createServer() {
  const server = new McpServer({
    name: "christian-reels-factory",
    version: "0.3.0",
  });

  server.registerTool(
    "project_status",
    {
      description: "Check the project status.",
    },
    async () => ({
      content: [{
        type: "text",
        text: "Christian Reels Factory MCP server is running.",
      }],
    })
  );

  server.registerTool(
    "generate_script",
    {
      description:
        "Generate an original Arabic Christian Reel script using Gemini AI.",
      inputSchema: z.object({
        topic: z.string().min(3).describe("Reel topic"),
        bible_reference: z.string().optional(),
        key_message: z.string().optional(),
        duration_seconds: z.number().int().min(20).max(60).optional(),
      }),
    },
    async ({
      topic,
      bible_reference,
      key_message,
      duration_seconds,
    }) => {
      const apiKey = (
        env as unknown as { GEMINI_API_KEY?: string }
      ).GEMINI_API_KEY;

      if (!apiKey) {
        return {
          content: [{
            type: "text",
            text: "خطأ: مفتاح Gemini غير موجود في Cloudflare Secrets.",
          }],
        };
      }

      const duration = duration_seconds ?? 35;

      const prompt = `
أنت كاتب ومعد محتوى متخصص في إنتاج Reels مسيحية عربية
لصفحة اسمها "الكتاب المقدس مسموع".

اكتب سيناريو أصليًا ومؤثرًا باللغة العربية المصرية البسيطة،
مع الحفاظ على احترام العقيدة المسيحية والنص الكتابي.

بيانات الريل:
الموضوع: ${topic}
المدة: ${duration} ثانية
المرجع الكتابي الذي قدمه المستخدم: ${bible_reference ?? "لم يتم تحديد مرجع"}
الرسالة الإضافية: ${key_message ?? "اختر رسالة مناسبة للموضوع"}

تعليمات الكتابة:
1. اكتب بداية جذابة تشد الانتباه من أول 3 ثوانٍ.
2. اجعل السيناريو مترابطًا وله فكرة واضحة.
3. استخدم لغة إنسانية مؤثرة وغير متكلفة.
4. لا تكرر العبارات التقليدية أو تملأ النص بكلام عام.
5. اجعل طول النص مناسبًا لمدة الريل.
6. أضف تأملًا روحيًا عمليًا يمس حياة المشاهد.
7. اختم بدعوة لطيفة للتفاعل والمشاركة.
8. لا تخترع آيات أو أرقام إصحاحات وأعداد.
9. إذا قدم المستخدم مرجعًا كتابيًا، اذكره دون اختلاق نص الآية،
   ونبّه إلى مراجعة النص من نسخة كتاب مقدس معتمدة.
10. إذا لم يقدم مرجعًا، لا تنسب آية محددة إلى الكتاب المقدس.

استخدم التنسيق التالي:

عنوان الريل:
البداية الجاذبة:
السيناريو:
التأمل:
الخاتمة:
المرجع الكتابي:
وصف المنشور:
الهاشتاجات:

أنتج نصًا جديدًا ومميزًا، وليس قالبًا ثابتًا.
`;

      try {
        const response = await fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent`,
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
                temperature: 0.85,
                maxOutputTokens: 2048,
              },
            }),
          }
        );

        const data: any = await response.json();

        if (!response.ok) {
          const message =
            data?.error?.message ?? "Unknown Gemini API error";

          return {
            content: [{
              type: "text",
              text: `فشل توليد السيناريو. HTTP ${response.status}\n${message}`,
            }],
          };
        }

        const generatedText =
          data?.candidates?.[0]?.content?.parts
            ?.map((part: any) => part.text ?? "")
            .join("")
            .trim();

        if (!generatedText) {
          return {
            content: [{
              type: "text",
              text: "لم يرجع Gemini نصًا. حاول مرة أخرى.",
            }],
          };
        }

        return {
          content: [{
            type: "text",
            text: `CHRISTIAN REEL - AI GENERATED\n\n${generatedText}`,
          }],
        };
      } catch (error) {
        return {
          content: [{
            type: "text",
            text: `حدث خطأ أثناء الاتصال بـ Gemini: ${
              error instanceof Error ? error.message : "Unknown error"
            }`,
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
