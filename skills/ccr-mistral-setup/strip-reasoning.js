/**
 * Custom transformer to strip the 'reasoning' field from requests.
 * Mistral (and other non-OpenAI-reasoning models) don't support this field.
 *
 * Install: copy to ~/.claude-code-router/strip-reasoning.js
 * Reference in config.json:
 *   "transformers": [{ "path": "C:/Users/<YOU>/.claude-code-router/strip-reasoning.js" }]
 */
class StripReasoningTransformer {
  name = "strip-reasoning";

  async transformRequestIn(requestBody, provider, context) {
    if (requestBody && typeof requestBody === "object" && "reasoning" in requestBody) {
      delete requestBody.reasoning;
    }
    return requestBody;
  }

  async transformResponseOut(response) {
    return response;
  }
}

module.exports = StripReasoningTransformer;
