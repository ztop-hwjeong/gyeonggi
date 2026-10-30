from decimal import Decimal

ESTIMATED_OUTPUT_TOKENS = 1024


def estimate_request_cost(input_tokens: int) -> Decimal:
    # OpenAI GPT-6 Luna Standard 단가 기준: https://developers.openai.com/api/docs/pricing
    if input_tokens > 272_000:
        input_rate, output_rate = Decimal("0.20"), Decimal("0.75")
    else:
        input_rate, output_rate = Decimal("0.10"), Decimal("0.50")
    return (input_tokens * input_rate + ESTIMATED_OUTPUT_TOKENS * output_rate) / 1_000_000
