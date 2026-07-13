exports.handler = async function (event, context) {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return { statusCode: 500, body: JSON.stringify({ error: "API key not configured" }) };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch (e) {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid JSON" }) };
  }

  const { topic, audience, occasion, duration, experience, fear, outcome } = body;

  const prompt = `You are a Toastmasters coach. Generate a speech prep plan as JSON.

Speaker: topic=${topic}, audience=${audience}, occasion=${occasion}, duration=${duration}, experience=${experience}, fear=${fear}, outcome=${outcome}

Return only valid JSON with these keys:
{
  "outline": { "hook": "1 sentence", "body": ["Point 1", "Point 2", "Point 3"], "close": "1 sentence" },
  "hooks": ["Hook 1", "Hook 2", "Hook 3"],
  "tips": ["Tip 1", "Tip 2", "Tip 3", "Tip 4", "Tip 5"],
  "warmup": ["Step 1", "Step 2", "Step 3", "Step 4", "Step 5"]
}

Be specific and tailored to this speaker. Tips must be practical and actionable. Hooks should be dramatic. Use Canadian cities (Vancouver, Toronto, Calgary) for any location examples. Return only valid JSON.`;

  try {
    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 800,
        messages: [{ role: "user", content: prompt }],
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      return { statusCode: response.status, body: JSON.stringify({ error: err }) };
    }

    const data = await response.json();
    const text = data.content[0].text;

    // Strip markdown code fences if present
    const jsonMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/) || [null, text];
    const jsonText = jsonMatch[1].trim();

    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: jsonText,
    };
  } catch (err) {
    return { statusCode: 500, body: JSON.stringify({ error: err.message }) };
  }
};
