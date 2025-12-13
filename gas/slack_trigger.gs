/**
 * Slack → GitHub Actions トリガー
 *
 * 【重要】Slackインタラクティブコンポーネントの仕様:
 * 1. リクエストは application/x-www-form-urlencoded 形式
 * 2. payloadパラメータにJSON文字列
 * 3. 3秒以内に200 OKを返す必要あり
 * 4. 追加メッセージはresponse_urlにPOST
 */

const GITHUB_OWNER = 'konkon034034';
const GITHUB_REPO = 'jinsei-soudan';

function getGitHubToken() {
  return PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN') || '';
}

// ========== 選択状態管理 ==========

function getSelections(key) {
  const data = PropertiesService.getScriptProperties().getProperty(key);
  return data ? JSON.parse(data) : {};
}

function setSelection(key, num, selected) {
  const props = PropertiesService.getScriptProperties();
  const sels = getSelections(key);
  sels[num] = selected;
  props.setProperty(key, JSON.stringify(sels));
}

function clearSelections(key) {
  PropertiesService.getScriptProperties().deleteProperty(key);
}

function countSelected(key, total) {
  const sels = getSelections(key);
  let count = 0;
  for (let i = 1; i <= total; i++) {
    // 明示的にtrue（✅選択）のものだけカウント
    if (sels[i] === true) count++;
  }
  return count;
}

function countExcluded(key, total) {
  const sels = getSelections(key);
  let count = 0;
  for (let i = 1; i <= total; i++) {
    // 明示的にfalse（❌除外）のものだけカウント
    if (sels[i] === false) count++;
  }
  return count;
}

// ========== メイン処理 ==========

function doPost(e) {
  console.log('=== doPost called ===');

  try {
    // Slackからのpayloadを取得
    let payload = null;

    // 方法1: e.parameter.payload (推奨)
    if (e.parameter && e.parameter.payload) {
      console.log('Found e.parameter.payload');
      payload = JSON.parse(e.parameter.payload);
    }
    // 方法2: postDataから取得
    else if (e.postData && e.postData.contents) {
      console.log('Trying postData.contents');
      const contents = e.postData.contents;

      if (contents.startsWith('{')) {
        // JSON形式
        payload = JSON.parse(contents);
      } else {
        // URL encoded形式
        const params = contents.split('&').reduce((acc, pair) => {
          const [key, val] = pair.split('=').map(decodeURIComponent);
          acc[key] = val;
          return acc;
        }, {});
        if (params.payload) {
          payload = JSON.parse(params.payload);
        }
      }
    }

    if (!payload) {
      console.log('No payload found');
      return ContentService.createTextOutput('No payload');
    }

    console.log('Payload type:', payload.type);

    // URL検証
    if (payload.type === 'url_verification') {
      return ContentService.createTextOutput(payload.challenge);
    }

    // ボタンクリック
    if (payload.type === 'block_actions') {
      const action = payload.actions[0];
      const actionId = action.action_id;
      const responseUrl = payload.response_url;

      console.log('Action:', actionId);
      console.log('Response URL:', responseUrl ? 'exists' : 'none');

      // 即座に空レスポンスを返す準備
      // 処理結果はresponse_urlに送信
      processAction(actionId, responseUrl);

      // 3秒以内に空の200 OKを返す（これが重要！）
      return ContentService.createTextOutput('');
    }

    return ContentService.createTextOutput('OK');

  } catch (err) {
    console.error('Error:', err.message);
    return ContentService.createTextOutput('Error: ' + err.message);
  }
}

function processAction(actionId, responseUrl) {
  console.log('Processing:', actionId);

  let message = '';

  try {
    // 台本行選択: use_line_{ch}_{num} / skip_line_{ch}_{num}
    if (actionId.startsWith('use_line_') || actionId.startsWith('skip_line_')) {
      const parts = actionId.split('_');
      const ch = parts[2];
      const num = parseInt(parts[3]);
      const isUse = actionId.startsWith('use_line_');

      setSelection('line_' + ch, num, isUse);
      const lineSel = countSelected('line_' + ch, 50);
      const imgSel = countSelected('img_' + ch, 10);

      if (isUse) {
        // ✅ 使う → メッセージを「選択済み」に置き換え
        sendToResponseUrl(responseUrl, `✅ 台本${num}行目を選択（計${lineSel}行 / 画像${imgSel}枚）`, true, false);
      } else {
        // ❌ 削除 → メッセージを削除
        sendToResponseUrl(responseUrl, '', false, true);
      }
      return; // 処理完了、以降のsendToResponseUrlをスキップ
    }

    // 画像選択: use_img_{ch}_{num} / skip_img_{ch}_{num}
    else if (actionId.startsWith('use_img_') || actionId.startsWith('skip_img_')) {
      const parts = actionId.split('_');
      const ch = parts[2];
      const num = parseInt(parts[3]);
      const isUse = actionId.startsWith('use_img_');

      setSelection('img_' + ch, num, isUse);
      const lineSel = countSelected('line_' + ch, 50);
      const imgSel = countSelected('img_' + ch, 10);

      if (isUse) {
        // ✅ 使う → メッセージを「選択済み」に置き換え
        sendToResponseUrl(responseUrl, `✅ 画像${num}を選択（計${imgSel}枚 / 台本${lineSel}行）`, true, false);
      } else {
        // ❌ 削除 → メッセージを削除
        sendToResponseUrl(responseUrl, '', false, true);
      }
      return; // 処理完了
    }

    // 動画生成: generate_{ch}
    else if (actionId.startsWith('generate_')) {
      const ch = actionId.replace('generate_', '');
      const imgCount = countSelected('img_' + ch, 10);
      const lineCount = countSelected('line_' + ch, 50);

      if (imgCount === 0 && lineCount === 0) {
        message = '⚠️ 画像または台本を選択してください';
      } else {
        // GitHub Actions起動
        const success = triggerGitHubAction(ch);
        if (success) {
          message = `🎬 ch${ch}の動画生成を開始！\n画像: ${imgCount}枚 | 台本: ${lineCount}行`;
          clearSelections('img_' + ch);
          clearSelections('line_' + ch);
        } else {
          message = '❌ GitHub Actions起動失敗';
        }
      }
    }

    // 再生成: regenerate_{ch}
    else if (actionId.startsWith('regenerate_')) {
      const ch = actionId.replace('regenerate_', '');
      clearSelections('img_' + ch);
      clearSelections('line_' + ch);
      triggerPrepare(ch);
      message = '🔄 再生成を開始しました';
    }

    // スキップ: skip_{ch}
    else if (actionId.startsWith('skip_')) {
      const ch = actionId.replace('skip_', '');
      clearSelections('img_' + ch);
      clearSelections('line_' + ch);
      message = '⏭️ スキップしました';
    }

    else {
      message = 'Unknown action: ' + actionId;
    }

  } catch (err) {
    console.error('Process error:', err);
    message = '❌ エラー: ' + err.message;
  }

  // response_urlにメッセージを送信
  if (responseUrl && message) {
    sendToResponseUrl(responseUrl, message);
  }
}

function sendToResponseUrl(url, text, replaceOriginal = false, deleteOriginal = false) {
  console.log('Sending to response_url:', text, 'replace:', replaceOriginal, 'delete:', deleteOriginal);

  try {
    const payload = {
      response_type: 'ephemeral',
      replace_original: replaceOriginal,
      delete_original: deleteOriginal,
      text: text
    };

    UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    console.log('Sent successfully');
  } catch (e) {
    console.error('Send error:', e);
  }
}

// ========== GitHub Actions ==========

function triggerGitHubAction(channelNum) {
  const token = getGitHubToken();
  if (!token) {
    console.error('GITHUB_TOKEN not set');
    return false;
  }

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/generate-video.yml/dispatches`;

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github.v3+json'
      },
      contentType: 'application/json',
      payload: JSON.stringify({
        ref: 'main',
        inputs: { channel: String(channelNum) }
      }),
      muteHttpExceptions: true
    });

    const code = resp.getResponseCode();
    console.log('GitHub response:', code);
    return code === 204;
  } catch (e) {
    console.error('GitHub error:', e);
    return false;
  }
}

function triggerPrepare(channelNum) {
  const token = getGitHubToken();
  if (!token) return false;

  const chIndex = { '27': '1', '24': '2', '23': '3' }[channelNum] || '0';
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/syouwa-morning-prepare.yml/dispatches`;

  try {
    UrlFetchApp.fetch(url, {
      method: 'post',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github.v3+json'
      },
      contentType: 'application/json',
      payload: JSON.stringify({
        ref: 'main',
        inputs: { channel_index: chIndex }
      }),
      muteHttpExceptions: true
    });
    return true;
  } catch (e) {
    console.error('Prepare error:', e);
    return false;
  }
}

// ========== テスト ==========

function testAction() {
  processAction('use_img_27_1', null);
  console.log('Count:', countSelected('img_27', 10));
  clearSelections('img_27');
}

function doGet(e) {
  return ContentService.createTextOutput('Slack Trigger GAS - POST only');
}
