/**
 * Slack → GitHub Actions トリガー + 画像/台本行 選択状態管理
 *
 * GAS URL: https://script.google.com/macros/s/AKfycbwvKV-ZXP9ecJAIwD-qdi6K7XF8HtZvK4X8JEEdNqqTijkAX2gMNWeYN3j9CuqUX8XI/exec
 *
 * 【重要】Slackインタラクティブコンポーネントの仕様:
 * - リクエストは application/x-www-form-urlencoded 形式
 * - payloadパラメータにJSON文字列が入っている
 * - 3秒以内にレスポンスを返す必要がある
 */

const GITHUB_OWNER = 'konkon034034';
const GITHUB_REPO = 'jinsei-soudan';

function getGitHubToken() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    throw new Error('GITHUB_TOKEN not set in Script Properties');
  }
  return token;
}

// ========== 選択状態管理 ==========

function getSelections(key) {
  const props = PropertiesService.getScriptProperties();
  const data = props.getProperty(key);
  return data ? JSON.parse(data) : {};
}

function setSelection(key, num, selected) {
  const props = PropertiesService.getScriptProperties();
  const sels = getSelections(key);
  sels[num] = selected;
  props.setProperty(key, JSON.stringify(sels));
  return sels;
}

function clearSelections(key) {
  PropertiesService.getScriptProperties().deleteProperty(key);
}

function countSelected(key, total) {
  const sels = getSelections(key);
  let count = 0;
  for (let i = 1; i <= total; i++) {
    if (sels[i] !== false) count++;
  }
  return count;
}

function getTotals(ch) {
  const props = PropertiesService.getScriptProperties();
  return {
    images: parseInt(props.getProperty('total_img_' + ch) || '10'),
    lines: parseInt(props.getProperty('total_line_' + ch) || '20')
  };
}

// ========== メイン処理 ==========

function doPost(e) {
  try {
    // Slackからのリクエストをパース
    // application/x-www-form-urlencoded形式でpayloadパラメータにJSONが入っている
    let payload;

    if (e.parameter && e.parameter.payload) {
      // Slackインタラクティブコンポーネントからのリクエスト
      payload = JSON.parse(e.parameter.payload);
      console.log('Slack payload received:', JSON.stringify(payload).substring(0, 500));
    } else if (e.postData && e.postData.contents) {
      // JSON形式のリクエスト（URL検証など）
      const contentType = e.postData.type || '';
      if (contentType.includes('application/json')) {
        payload = JSON.parse(e.postData.contents);
      } else if (contentType.includes('application/x-www-form-urlencoded')) {
        // フォームデータからpayloadを取得
        const params = {};
        e.postData.contents.split('&').forEach(pair => {
          const [key, value] = pair.split('=');
          params[decodeURIComponent(key)] = decodeURIComponent(value || '');
        });
        if (params.payload) {
          payload = JSON.parse(params.payload);
        }
      }
    }

    if (!payload) {
      console.error('No payload found in request');
      return ContentService.createTextOutput('No payload');
    }

    // URL検証（Slack App設定時）
    if (payload.type === 'url_verification') {
      return ContentService.createTextOutput(payload.challenge);
    }

    // ボタンクリック処理
    if (payload.type === 'block_actions') {
      const result = handleAction(payload);
      // Slackには即座にJSON形式でレスポンスを返す
      return ContentService.createTextOutput(JSON.stringify(result))
        .setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService.createTextOutput('OK');

  } catch (err) {
    console.error('doPost error:', err.message, err.stack);
    // エラー時も200 OKを返す（Slackがリトライしないように）
    return ContentService.createTextOutput(JSON.stringify({
      response_type: 'ephemeral',
      text: '❌ エラー: ' + err.message
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function handleAction(payload) {
  const action = payload.actions[0];
  const actionId = action.action_id;
  const responseUrl = payload.response_url;

  console.log('Action ID:', actionId);

  // === 画像選択: use_img_{ch}_{num} / skip_img_{ch}_{num} ===
  if (actionId.startsWith('use_img_') || actionId.startsWith('skip_img_')) {
    const parts = actionId.split('_');
    const ch = parts[2];
    const num = parseInt(parts[3]);
    const selected = actionId.startsWith('use_img_');

    setSelection('img_' + ch, num, selected);
    const totals = getTotals(ch);
    const imgCount = countSelected('img_' + ch, totals.images);
    const lineCount = countSelected('line_' + ch, totals.lines);

    const msg = selected
      ? `✅ 画像${num}を選択\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`
      : `❌ 画像${num}を除外\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`;

    return { response_type: 'ephemeral', text: msg };
  }

  // === 台本行選択: use_line_{ch}_{num} / skip_line_{ch}_{num} ===
  if (actionId.startsWith('use_line_') || actionId.startsWith('skip_line_')) {
    const parts = actionId.split('_');
    const ch = parts[2];
    const num = parseInt(parts[3]);
    const selected = actionId.startsWith('use_line_');

    setSelection('line_' + ch, num, selected);
    const totals = getTotals(ch);
    const imgCount = countSelected('img_' + ch, totals.images);
    const lineCount = countSelected('line_' + ch, totals.lines);

    const msg = selected
      ? `✅ 台本${num}行目を選択\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`
      : `❌ 台本${num}行目を除外\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`;

    return { response_type: 'ephemeral', text: msg };
  }

  // === 動画生成: generate_{ch} ===
  if (actionId.startsWith('generate_')) {
    const ch = actionId.replace('generate_', '');
    const totals = getTotals(ch);
    const imgCount = countSelected('img_' + ch, totals.images);
    const lineCount = countSelected('line_' + ch, totals.lines);

    if (imgCount === 0 || lineCount === 0) {
      return {
        response_type: 'ephemeral',
        text: `⚠️ 画像と台本を選択してください\n現在: 画像${imgCount}枚, 台本${lineCount}行`
      };
    }

    // GitHub Actions トリガー（非同期で実行）
    triggerWorkflowAsync(ch, imgCount, lineCount, responseUrl);

    // 選択状態をクリア
    clearSelections('img_' + ch);
    clearSelections('line_' + ch);

    return {
      response_type: 'ephemeral',
      text: `🎬 ch${ch}の動画生成を開始！\n画像: ${imgCount}枚 | 台本: ${lineCount}行`
    };
  }

  // === 再生成: regenerate_{ch} ===
  if (actionId.startsWith('regenerate_')) {
    const ch = actionId.replace('regenerate_', '');
    clearSelections('img_' + ch);
    clearSelections('line_' + ch);
    triggerPrepareAsync(ch, responseUrl);
    return { response_type: 'ephemeral', text: '🔄 再生成中...' };
  }

  // === スキップ: skip_{ch} ===
  if (actionId.startsWith('skip_')) {
    const ch = actionId.replace('skip_', '');
    clearSelections('img_' + ch);
    clearSelections('line_' + ch);
    return { response_type: 'ephemeral', text: '⏭️ スキップしました' };
  }

  return { response_type: 'ephemeral', text: 'OK' };
}

// ========== GitHub Actions（非同期） ==========

function triggerWorkflowAsync(channelNum, imgCount, lineCount, responseUrl) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/generate-video.yml/dispatches`;

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      headers: {
        'Authorization': 'Bearer ' + getGitHubToken(),
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
      },
      payload: JSON.stringify({
        ref: 'main',
        inputs: { channel: String(channelNum) }
      }),
      muteHttpExceptions: true
    });

    const code = resp.getResponseCode();
    console.log('GitHub API response:', code);

    if (responseUrl) {
      if (code === 204) {
        sendToSlack(responseUrl, `✅ ch${channelNum}の動画生成をGitHub Actionsで開始しました！\n画像: ${imgCount}枚 | 台本: ${lineCount}行`);
      } else {
        sendToSlack(responseUrl, `❌ GitHub エラー(${code}): ${resp.getContentText()}`);
      }
    }
  } catch (e) {
    console.error('triggerWorkflow error:', e);
    if (responseUrl) {
      sendToSlack(responseUrl, '❌ エラー: ' + e.message);
    }
  }
}

function triggerPrepareAsync(channelNum, responseUrl) {
  const chIndex = { '27': '1', '24': '2', '23': '3' }[channelNum] || '0';
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/syouwa-morning-prepare.yml/dispatches`;

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      headers: {
        'Authorization': 'Bearer ' + getGitHubToken(),
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
      },
      payload: JSON.stringify({
        ref: 'main',
        inputs: { channel_index: chIndex }
      }),
      muteHttpExceptions: true
    });

    const code = resp.getResponseCode();
    console.log('GitHub API response:', code);

    if (responseUrl) {
      if (code === 204) {
        sendToSlack(responseUrl, `🔄 ch${channelNum}の再生成を開始しました！`);
      } else {
        sendToSlack(responseUrl, `❌ GitHub エラー(${code})`);
      }
    }
  } catch (e) {
    console.error('triggerPrepare error:', e);
    if (responseUrl) {
      sendToSlack(responseUrl, '❌ エラー: ' + e.message);
    }
  }
}

function sendToSlack(url, text) {
  if (!url) return;
  try {
    UrlFetchApp.fetch(url, {
      method: 'post',
      headers: { 'Content-Type': 'application/json' },
      payload: JSON.stringify({
        response_type: 'ephemeral',
        text: text
      })
    });
  } catch (e) {
    console.error('sendToSlack error:', e);
  }
}

// ========== テスト・デバッグ ==========

function testDoPost() {
  // Slackからのリクエストをシミュレート
  const mockPayload = {
    type: 'block_actions',
    actions: [{
      action_id: 'use_img_27_1',
      value: '{"img_num": 1}'
    }],
    response_url: null
  };

  const mockEvent = {
    parameter: {
      payload: JSON.stringify(mockPayload)
    }
  };

  const result = doPost(mockEvent);
  console.log('Result:', result.getContent());
}

function doGet(e) {
  return ContentService.createTextOutput('GAS Slack Trigger is running. POST only.');
}
