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

  const prompt = `You are a seasoned Toastmasters coach with hundreds of hours on stage and thousands of speakers coached. A speaker has filled out a pre-speech prep form. Generate a speech prep plan based on their answers.

Speaker Details:
- Speech Topic: ${topic}
- Audience: ${audience}
- Occasion: ${occasion}
- Speech Duration: ${duration}
- Experience Level: ${experience}
- Biggest Fear: ${fear}
- Desired Outcome (what they want the audience to feel/do): ${outcome}

Generate the following in JSON format with these exact keys:

{
  "outline": {
    "hook": "A compelling opening section description (2–3 sentences explaining what to do)",
    "body": ["Point 1 description", "Point 2 description", "Point 3 description"],
    "close": "A powerful closing section description (2–3 sentences)"
  },
  "hooks": [
    "Full opening hook #1 — a complete sentence or two they could actually say",
    "Full opening hook #2 — a complete sentence or two they could actually say",
    "Full opening hook #3 — a complete sentence or two they could actually say"
  ],
  "tips": [
    "Personalized tip #1",
    "Personalized tip #2",
    "Personalized tip #3",
    "Personalized tip #4",
    "Personalized tip #5"
  ],
  "warmup": [
    "Warmup step 1 (with timing, e.g. '2 minutes: ...')",
    "Warmup step 2",
    "Warmup step 3",
    "Warmup step 4",
    "Warmup step 5"
  ]
}

For the tips: give only advice that a seasoned Toastmasters coach would give — practical, specific, and grounded in real on-stage experience. Every tip must be directly actionable and tailored to this speaker's topic, audience, occasion, experience level, and fear. No generic advice. No mention of the 'rule of three' or any academic or textbook frameworks. Tips must sound like they come from someone who has stood on stage hundreds of times and coached thousands of speakers through the same nerves and challenges. Make the hooks dramatic and memorable. Be specific and tailored throughout. Return only valid JSON.`;

  try {
    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
        max_tokens: 2000,
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
