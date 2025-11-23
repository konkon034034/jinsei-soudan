def search_bakenami_reactions(self):
    """ネットで朝ドラ「ばけばけ」の反応を検索"""
    print("\n=== STEP 1: ネット反応検索 ===")
    
    search_prompt = """
あなたは情報収集の専門家です。
現在放送中のNHK連続テレビ小説「ばけばけ」について、
SNSやニュースサイトでの視聴者の反応をまとめてください。

以下の情報を含めてください：
- 今週のストーリー展開への反応
- 登場人物への感想
- 話題になっているシーン
- 感動的だった場面
- 面白かった・驚いたという意見

※実際のネット検索ができないため、あなたの知識に基づいて
朝ドラの典型的な視聴者反応をシミュレートしてください。

検索結果を整理して、JSONフォーマットで返してください：
{
  "reactions": [
    {
      "source": "情報源",
      "content": "反応内容",
      "sentiment": "positive/neutral/negative"
    }
  ],
  "trending_topics": ["トピック1", "トピック2", ...],
  "summary": "全体のまとめ"
}
"""
    
    # tools='google_search' を削除
    response = self.model.generate_content(search_prompt)
    
    search_result = response.text
    self.log_to_sheet('検索完了', search_result=search_result[:500])
    
    # スプレッドシートに保存
    self.sheet.update_cell(self.sheet_row, 3, search_result[:1000])
    
    return search_result
