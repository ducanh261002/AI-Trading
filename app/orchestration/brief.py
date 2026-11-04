"""Deterministic Vietnamese research reports from completed Agent evidence."""
NAMES = {"ema_rsi": "EMA + RSI", "macd_atr": "MACD + EMA + ATR", "bollinger_volume": "Bollinger + Volume"}


def research_brief(run, candles):
    tasks = {task["agent_id"]: task for task in run["tasks"]}
    backtest = (tasks.get("backtest", {}).get("result") or {}).get("results", [])
    signal = (tasks.get("signal", {}).get("result") or {}).get("signal", "HOLD")
    comparisons, warnings = [], []
    count = len(candles or [])
    if count < 500:
        warnings.append(f"Mẫu hiện có {count} nến, còn ngắn để đánh giá độ bền của chiến lược.")
    if not backtest:
        warnings.append("Chưa có backtest hoàn tất; Agent cần ít nhất 120 nến đã đóng.")
    for item in backtest:
        testing = (item.get("holdout") or {}).get("testing")
        comparisons.append({"strategy": item["strategy"], "name": NAMES.get(item["strategy"], item["strategy"]),
                            "trades": item["trade_count"], "pnl": item["final_equity"] - item["initial_equity"],
                            "return_percent": item["net_return"] * 100,
                            "drawdown_percent": item["max_drawdown"] * 100,
                            "win_percent": None if item["win_rate"] is None else item["win_rate"] * 100,
                            "test_return_percent": None if testing is None else testing["net_return"] * 100,
                            "test_trades": None if testing is None else testing["trade_count"], "cached": item.get("cached", False)})
    if any(row["test_trades"] is None or row["test_trades"] < 30 for row in comparisons):
        warnings.append("Phần kiểm thử tách riêng chưa đủ 30 giao dịch mỗi chiến lược; chưa có kết luận đáng tin cậy.")
    news = tasks.get("news", {})
    if news.get("status") != "Completed":
        warnings.append("Chưa có nguồn tin tức sẵn sàng; nhận xét hiện dựa trên giá và nến.")
    failed = [task["agent_id"] for task in run["tasks"] if task["status"] == "Error"]
    if failed:
        warnings.append("Nhiệm vụ lỗi: " + ", ".join(failed))
    eligible = [row for row in comparisons if count >= 500 and row["test_trades"] is not None
                and row["test_trades"] >= 30 and row["test_return_percent"] > 0]
    candidate = max(eligible, key=lambda row: row["test_return_percent"]) if eligible and not failed else None
    activity = "tái sử dụng kết quả khi dữ liệu không đổi" if backtest and all(row["cached"] for row in comparisons) else "chạy kiểm thử và so sánh"
    summary = f"Backtest Agent đã {activity} {len(backtest)} chiến lược cho {run['symbol']} / {run['interval']}. Signal Agent hiện báo {signal}."
    if comparisons:
        positive = sum(row["pnl"] > 0 for row in comparisons)
        negative = sum(row["pnl"] < 0 for row in comparisons)
        summary += f" Trong mẫu này: {positive} chiến lược có lãi, {negative} bị lỗ, {len(comparisons) - positive - negative} hòa vốn."
    return {"run_id": run["id"], "symbol": run["symbol"], "interval": run["interval"],
            "finished_at": run["finished_at"], "sample_candles": count,
            "data_start": candles[0]["open_time"] if candles else None,
            "data_end": candles[-1]["close_time"] if candles else None,
            "summary": summary, "comparisons": comparisons, "warnings": warnings,
            "conclusion": f"{candidate['name']} chỉ là ứng viên để nghiên cứu/quan sát thêm." if candidate else "Chưa đủ bằng chứng để đề xuất chiến lược tự động.",
            "execution": "Chu kỳ chỉ phân tích, không mở lệnh." if run["analysis_only"] else "Chu kỳ có kiểm tra paper; xem kết quả Execution Agent.",
            "analysis_only": bool(run["analysis_only"]), "profitability_certified": False}
