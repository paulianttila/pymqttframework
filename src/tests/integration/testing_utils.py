def get_metric(result, metric) -> float:
    matched_lines = [line for line in result.split("\n") if line.startswith(metric)]
    for line in matched_lines:
        val = float(line.replace(metric, "").strip())
        print(f"{metric}={val}")
        return val
    return float("NaN")


def check_metrics(response):
    assert get_metric(response.text, "do_update_exceptions_total") == 0
    assert get_metric(response.text, "manual_trigger_counter_total") == 3
    assert get_metric(response.text, "do_update_count") > 5
    assert get_metric(response.text, "interval_trigger_counter_total") > 5
    assert get_metric(response.text, "cron_trigger_counter_total") > 5
    assert get_metric(response.text, "mqtt_messages_sent_total") > 5
    assert get_metric(response.text, "mqtt_messages_received_total") > 4
