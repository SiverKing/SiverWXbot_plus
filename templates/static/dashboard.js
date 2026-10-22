/* ============================================================
   SiverWXBot 管理面板脚本
   从 templates/dashboard.html 的内联 <script> 块迁出（2026-10）。
   分两部分：
     一、主逻辑（svModal 工具 + 单个 $(function(){...}) 闭包，不可拆分）
     二、行内 onchange 调用的全局函数（必须保持全局作用域）
   引入方式：HTML 中 url_for('static', filename='dashboard.js') + ?v= 版本号
   ============================================================ */

// ===== svModal：自定义弹窗工具（替代浏览器 alert/confirm） =====
// 全站唯一允许富文本的路径：_show 的 body 用 .html() 渲染，只准传「开发者写死的常量
// HTML」（标题、按钮、图标走 .text()）。服务端数据、微信消息、用户输入一律 .text()，
// 不要从这里过——否则等于把日志区刚堵上的洞在弹窗里重开一遍。
// 需要在正文里展示服务端数据时，用 bodyNode（调用方自己用 .text() 构建 DOM），
// 走 *_Node 系列方法，不要把拼好的字符串塞进 body。
var svModal = (function(){
  function _show(opts) {
    var $overlay = $('#sv-modal-overlay');
    $('#sv-modal-icon').html(opts.icon || '');
    $('#sv-modal-title').text(opts.title || '');
    if (opts.bodyNode) {
      // 调用方已用 .text()/DOM 构建好正文：整段 append，不经 .html()
      $('#sv-modal-body').empty().append(opts.bodyNode);
    } else {
      $('#sv-modal-body').html(opts.body || '');
    }
    var $btns = $('#sv-modal-btns').empty();
    (opts.buttons || []).forEach(function(btn){
      var baseStyle = 'padding:8px 22px;border-radius:7px;font-weight:600;font-size:13.5px;cursor:pointer;border:none;transition:opacity .15s;';
      var $b = $('<button>').attr('style', baseStyle).css(btn.css || {background:'#576B95',color:'#fff'}).text(btn.text);
      $b.on('click', function(){ _close(); if(btn.action) btn.action(); });
      $btns.append($b);
    });
    $overlay.css('display','flex');
  }
  function _close(){ $('#sv-modal-overlay').hide(); }
  return {
    alert: function(msg, title){ _show({
      icon: '<i class="bi bi-info-circle-fill" style="color:var(--primary);font-size:36px;"></i>',
      title: title||'提示', body: msg,
      buttons: [{text:'确定', css:{background:'var(--primary)',color:'#fff'}}]
    }); },
    success: function(msg, title){ _show({
      icon: '<i class="bi bi-check-circle-fill" style="color:#07C160;font-size:36px;"></i>',
      title: title||'成功', body: msg,
      buttons: [{text:'确定', css:{background:'#07C160',color:'#fff'}}]
    }); },
    // 正文由调用方用 .text()/DOM 安全构建（服务端数据、用户输入一律走这两个）
    successNode: function($body, title){ _show({
      icon: '<i class="bi bi-check-circle-fill" style="color:#07C160;font-size:36px;"></i>',
      title: title||'成功', bodyNode: $body,
      buttons: [{text:'确定', css:{background:'#07C160',color:'#fff'}}]
    }); },
    warnNode: function($body, title){ _show({
      icon: '<i class="bi bi-exclamation-triangle-fill" style="color:#FFC300;font-size:36px;"></i>',
      title: title||'请注意', bodyNode: $body,
      buttons: [{text:'知道了', css:{background:'#FFC300',color:'#fff'}}]
    }); },
    error: function(msg, title){ _show({
      icon: '<i class="bi bi-x-circle-fill" style="color:#FA5151;font-size:36px;"></i>',
      title: title||'错误', body: msg,
      buttons: [{text:'关闭', css:{background:'#f2f2f2',color:'#333',border:'1px solid #ddd'}}]
    }); },
    confirm: function(msg, onOk, title, okText, cancelText){ _show({
      icon: '<i class="bi bi-question-circle-fill" style="color:#FFC300;font-size:36px;"></i>',
      title: title||'确认', body: msg,
      buttons: [
        {text: cancelText||'取消', css:{background:'#f2f2f2',color:'#333',border:'1px solid #ddd'}},
        {text: okText||'确定', css:{background:'var(--primary)',color:'#fff'}, action: onOk}
      ]
    }); },
    conflict: function(msg, onReload, onForce){ _show({
      icon: '<i class="bi bi-exclamation-triangle-fill" style="color:#FFC300;font-size:36px;"></i>',
      title: '配置已被其他改动更新',
      body: msg,
      buttons: [
        {text:'取消', css:{background:'#f2f2f2',color:'#333',border:'1px solid #ddd'}},
        {text:'重新加载', css:{background:'#f2f2f2',color:'#333',border:'1px solid #ddd'}, action: onReload},
        {text:'强制覆盖', css:{background:'#FA5151',color:'#fff'}, action: onForce}
      ]
    }); },
    warnUpdate: function(newVer, onContinue){ _show({
      icon: '<i class="bi bi-arrow-up-circle-fill" style="color:#FFC300;font-size:36px;"></i>',
      title: '发现新版本',
      body: '检测到新版本可用：<b>' + newVer + '</b><br><br>建议更新后再使用，继续使用旧版本可能存在问题。',
      buttons: [
        {text:'取消', css:{background:'#f2f2f2',color:'#333',border:'1px solid #ddd'}},
        {text:'去更新', css:{background:'#576B95',color:'#fff'}, action: function(){ $('#update-card')[0].scrollIntoView({behavior:'smooth'}); }},
        {text:'继续启动', css:{background:'#FFC300',color:'#fff'}, action: onContinue}
      ]
    }); },
    warnActivate: function(onContinue){ _show({
      icon: '<i class="bi bi-shield-exclamation" style="color:#FA5151;font-size:36px;"></i>',
      title: '本设备 wxautox4 未激活',
      body: '程序依赖的内核库 <b>wxautox4</b> 尚未激活，<br>可能导致机器人无法正常使用。<br><br>建议先完成授权后再启动。',
      buttons: [
        {text:'取消', css:{background:'#f2f2f2',color:'#333',border:'1px solid #ddd'}},
        {text:'获取激活码授权', css:{background:'#576B95',color:'#fff'}, action: function(){ window.open('https://www.siverking.online/static/img/siver_wx.jpg','_blank'); }},
        {text:'已有激活码？点我激活', css:{background:'#07C160',color:'#fff'}, action: function(){ showActivateDialog(); }},
        {text:'继续启动', css:{background:'#FA5151',color:'#fff'}, action: onContinue}
      ]
    }); }
  };
})();

$(function(){
  // ===== Summernote Init =====
  $('#group_welcome_msg').summernote({
    height:200, lang:'zh-CN',
    toolbar:[
      ['style',['style']],['font',['bold','italic','underline','clear']],
      ['para',['ul','ol','paragraph']],['insert',['link']],['view',['codeview']]
    ]
  });

  // ===== 接口配置：API Key 遮罩显示（前5位 + *** + 后5位）=====
  function maskApiKey(key) {
    if (!key) return '';
    if (key.length <= 10) return key;
    return key.slice(0, 5) + '*'.repeat(key.length - 10) + key.slice(-5);
  }

  function getSiverPanelBaseUrl(){
    return String($('#siver-panel-card').data('baseUrl') || 'https://panel.siver.top').replace(/\/+$/, '');
  }

  function normalizeSiverPanelSlug(value){
    return String(value || '').trim().toLowerCase();
  }

  function isValidSiverPanelSlug(slug){
    return /^[a-z0-9](?:[a-z0-9-]{3,30}[a-z0-9])?$/.test(slug);
  }

  function buildSiverPanelUrl(slug){
    slug = normalizeSiverPanelSlug(slug);
    return slug ? (getSiverPanelBaseUrl() + '/panel/' + slug) : '';
  }

  function updateSiverPanelUrlPreview(){
    var slug = normalizeSiverPanelSlug($('#siver_panel_slug').val());
    $('#siver_panel_slug').val(slug);
    var previewUrl = buildSiverPanelUrl(slug);
    $('#siver-panel-url-preview').text(previewUrl || '填写安全入口后，这里会显示远程访问地址');
  }

  function renderSiverPanelStatus(data){
    data = data || {};
    var state = data.state || (data.enabled ? 'idle' : 'disabled');
    var stateMap = {
      disabled:   {text:'已关闭', color:'#9ca3af', sub:'关闭后不会自动连接远程服务。'},
      idle:       {text:'待连接', color:'#94a3b8', sub:'已保存配置，等待手动连接或下次启动自动连接。'},
      connecting: {text:'连接中', color:'#3b82f6', sub:'正在连接远程服务，请稍候。'},
      connected:  {text:'已连接', color:'#10b981', sub:'远程访问服务已建立连接，可通过公网地址访问面板。'},
      retrying:   {text:'重试中', color:'#f59e0b', sub:'检测到网络异常，正在按策略自动重试。'},
      disconnected:{text:'已断开', color:'#f97316', sub:'远程访问服务已断开，可重新点击连接。'},
      error:      {text:'连接失败', color:'#ef4444', sub:'本次连接未成功，请根据服务反馈检查配置。'}
    };
    var current = stateMap[state] || stateMap.idle;
    var slug = data.slug || normalizeSiverPanelSlug($('#siver_panel_slug').val());
    var exampleUrl = data.example_url || buildSiverPanelUrl(slug);
    var currentUrl = data.panel_url || exampleUrl;
    var retryText = data.enabled ? ((data.retry_count || 0) + ' / ' + (data.retry_max || 3)) : '未启用';
    var bindText = data.device_bound ? '已绑定' : '未绑定';

    $('#siver-panel-status-dot').css('background', current.color);
    $('#siver-panel-status-text').text(current.text);
    $('#siver-panel-status-sub').text(current.sub);
    $('#siver-panel-last-message').text(data.last_message || current.sub);
    $('#siver-panel-current-url').html(currentUrl ? '<a href="' + currentUrl + '" target="_blank" rel="noopener">' + currentUrl + '</a>' : '未生成');
    $('#siver-panel-last-sync').text(data.updated_at ? ('更新于 ' + data.updated_at) : '-');

    $('#siver-panel-quick-state').text(current.text).css('color', current.color);
    $('#siver-panel-quick-bind').text(bindText);
    $('#siver-panel-quick-expire').text(data.service_expire_at || '未获取');
    $('#siver-panel-quick-retry').text(retryText);

    updateSiverPanelUrlPreview();
    if(state === 'connecting' || state === 'retrying'){
      $('#btn-siver-panel-connect').prop('disabled', true).html('<i class="bi bi-hourglass-split"></i> 连接中...');
    } else {
      $('#btn-siver-panel-connect').prop('disabled', false).html('<i class="bi bi-plug"></i> ' + (state === 'connected' ? '重新连接' : '连接远程服务'));
    }
  }

  function refreshSiverPanelStatus(){
    return $.getJSON('/api/siver-panel/status')
      .done(function(res){
        if(res.status === 'success' && res.data){
          renderSiverPanelStatus(res.data);
        } else {
          renderSiverPanelStatus({
            state:'error',
            enabled: $('#siver_panel_enabled').is(':checked'),
            last_message: res.message || '无法获取远程服务状态'
          });
        }
      })
      .fail(function(xhr){
        renderSiverPanelStatus({
          state:'error',
          enabled: $('#siver_panel_enabled').is(':checked'),
          last_message: '远程服务状态获取失败：' + xhr.status
        });
      });
  }

  function pollSiverPanelStatusForModal(options){
    options = options || {};
    var maxAttempts = options.maxAttempts || 36;
    var intervalMs = options.intervalMs || 700;
    var attempt = 0;

    function doneWithStatus(data){
      renderSiverPanelStatus(data || {});
      var state = (data && data.state) || 'idle';
      var message = (data && data.last_message) || '远程服务状态已更新';
      var panelUrl = (data && data.panel_url) || '';

      if(state === 'connected'){
        var body = message;
        if(panelUrl){
          body += '<br><br><a href="' + panelUrl + '" target="_blank" rel="noopener">' + panelUrl + '</a>';
        }
        svModal.success(body, '连接成功');
      } else if(state === 'error' || state === 'disconnected' || state === 'disabled'){
        svModal.error(message, '连接结果');
      } else {
        svModal.alert(message, '连接处理中');
      }
    }

    function requestStatus(){
      attempt += 1;
      $.getJSON('/api/siver-panel/status')
        .done(function(res){
          var data = (res.status === 'success' && res.data) ? res.data : {
            state:'error',
            last_message:(res && res.message) || '无法获取远程服务状态'
          };
          var state = data.state || 'idle';
          renderSiverPanelStatus(data);

          if(state === 'connecting' || (state === 'retrying' && attempt < maxAttempts)){
            setTimeout(requestStatus, intervalMs);
            return;
          }

          doneWithStatus(data);
        })
        .fail(function(xhr){
          if(attempt < maxAttempts){
            setTimeout(requestStatus, intervalMs);
            return;
          }
          var data = {
            state:'error',
            last_message:'远程服务状态获取失败：' + xhr.status
          };
          doneWithStatus(data);
        });
    }

    requestStatus();
  }

  function connectSiverPanel(){
    var enabled = $('#siver_panel_enabled').is(':checked');
    var activationCode = $('#siver_panel_activation_code').val().trim();
    var slug = normalizeSiverPanelSlug($('#siver_panel_slug').val()).replace(/[^a-z0-9-]/g, '');
    $('#siver_panel_slug').val(slug);
    updateSiverPanelUrlPreview();

    if(!enabled){
      svModal.error('请先开启远程访问服务开关。');
      return;
    }
    if(!activationCode){
      svModal.error('请先填写远程访问激活码。');
      return;
    }
    if(!isValidSiverPanelSlug(slug)){
      svModal.error('安全入口格式不正确，请使用 5-32 位的小写字母、数字或连字符，且不能以连字符开头或结尾。');
      return;
    }

    renderSiverPanelStatus({
      state:'connecting',
      enabled:true,
      slug:slug,
      last_message:'正在保存配置并发起远程连接，请稍候...'
    });

    saveConfig(function(){
      requestRemoteConnect({showConnectingState:false});
    });
  }
  // 聚焦：若正显示遮罩值则清空，方便输入新 Key
  $(document).on('focus', '.api-key-input', function(){
    var masked = $(this).data('masked') || '';
    if (masked && $(this).val() === masked) {
      $(this).val('').attr('placeholder', '输入新 Key，留空则保持原值');
    }
  });
  // 失焦：若未填写则恢复遮罩显示
  $(document).on('blur', '.api-key-input', function(){
    if ($(this).val() === '') {
      var masked = $(this).data('masked') || '';
      $(this).val(masked).attr('placeholder', 'sk-...');
    }
  });

  function getApiConfigFromItem($item){
    var $k = $item.find('.api-key-input');
    var typedKey = $k.val();
    var maskedKey = $k.data('masked') || '';
    var realKey = $k.data('real-key') || '';
    var keyToUse = (typedKey === maskedKey || typedKey === '') ? realKey : typedKey;
    return {
      sdk: $item.find('.api-sdk-select').val(),
      model: $item.find('.api-model-input').val(),
      url: $item.find('.api-url-input').val(),
      key: keyToUse
    };
  }

  // ===== 接口配置：单选框高亮 + 当前使用 badge =====
  $(document).on('change', '.api-radio', function(){
    $('.api-config-item').css({'border-color':'var(--border)', 'background':'var(--card)'});
    $('.api-active-badge').hide();
    $(this).closest('.api-config-item').css({'border-color':'var(--primary)', 'background':'#f6fff9'});
    $(this).closest('.api-config-item').find('.api-active-badge').show();
  });

  // ===== 接口配置：删除（至少保留 2 个）=====
  $(document).on('click', '.btn-remove-api-config', function(){
    if($('.api-config-item').length <= 2){ svModal.alert('至少保留 2 个接口配置'); return; }
    var $removedItem = $(this).closest('.api-config-item');
    var removedIndex = $('.api-config-item').index($removedItem);
    var wasSelected = $removedItem.find('.api-radio').is(':checked');
    var fallbackSelections = [];
    $('.api-config-item').each(function(i){
      if(i === removedIndex) return;
      var fallbackIndex = parseApiIndex($(this).find('.api-fallback-select').val());
      if(fallbackIndex === removedIndex) fallbackIndex = -1;
      else if(fallbackIndex > removedIndex) fallbackIndex -= 1;
      fallbackSelections.push({item:this, index:fallbackIndex});
    });
    $removedItem.remove();

    // 删除接口后，所有引用该下标的配置都要同步前移或回到默认值。
    $('.chat-api-select, .group-api-select').each(function(){
      var index = parseApiIndex($(this).val());
      if(index === removedIndex) index = -1;
      else if(index > removedIndex) index -= 1;
      $(this).val(String(index));
    });
    $('#chat_image_recognition_api, #group_image_recognition_api').each(function(){
      var index = parseApiIndex($(this).val());
      if(index === removedIndex) index = Math.min(removedIndex, $('.api-config-item').length - 1);
      else if(index > removedIndex) index -= 1;
      $(this).val(String(Math.max(0, index)));
    });

    renumberApiConfigs();
    if(wasSelected){
      var nextSelectedIndex = Math.min(removedIndex, $('.api-config-item').length - 1);
      $('.api-config-item').eq(nextSelectedIndex).find('.api-radio')
        .prop('checked', true).trigger('change');
    }
    syncApiConfigsList();
    fallbackSelections.forEach(function(selection){
      $(selection.item).find('.api-fallback-select').val(String(selection.index));
    });
    refreshApiReferenceDropdowns();
    refreshApiFallbackOptions();
  });

  // ===== 接口配置：测试当前选中接口 =====
  $('#btn-test-api-config').click(function(){
    var $btn = $(this);
    var $item = $('.api-config-item').has('.api-radio:checked').first();
    if(!$item.length){
      svModal.error('请先选择一个接口配置');
      return;
    }
    var apiConfig = getApiConfigFromItem($item);
    if(!apiConfig.sdk){
      svModal.error('请先选择当前接口的 SDK');
      return;
    }
    if(!apiConfig.key || !apiConfig.url || !apiConfig.model){
      svModal.error('请先填写当前选中接口的 API Key、Base URL 和模型名称');
      return;
    }
    var idx = $('.api-config-item').index($item) + 1;
    $btn.prop('disabled', true).html('<i class="bi bi-hourglass-split"></i> 测试中...');
    $.ajax({
      url: '/test_api_config',
      method: 'POST',
      contentType: 'application/json',
      dataType: 'json',
      timeout: 140000,
      data: JSON.stringify({api_config: apiConfig}),
      success: function(res){
        if(res.status === 'success'){
          var d = res.data || {};
          var cleanedHint = d.cleaned ? '<br><br>检测到思考标签，已按当前清洗规则处理测试返回。' : '';
          svModal.success(
            '接口 ' + idx + ' 可用<br>' +
            '耗时：' + (d.elapsed_ms || '-') + ' ms<br>' +
            '文字回复：<span style="color:#07C160;font-weight:600;">可用</span><br>' +
            '返回：<code>' + $('<div>').text(d.reply || '').html() + '</code>' +
            cleanedHint,
            '测试成功'
          );
        } else {
          svModal.error(res.message || '接口测试失败', '测试失败');
        }
      },
      error: function(xhr){
        var msg = '接口测试请求失败';
        if(xhr.responseJSON && xhr.responseJSON.message) msg = xhr.responseJSON.message;
        else if(xhr.status) msg += '：HTTP ' + xhr.status;
        svModal.error(msg, '测试失败');
      },
      complete: function(){
        $btn.prop('disabled', false).html('<i class="bi bi-activity"></i> 测试可用性');
      }
    });
  });

  // ===== 接口配置：添加 =====
  $('#btn-add-api-config').click(function(){
    var html=
      '<div class="api-config-item" style="border:1px solid var(--border);border-radius:6px;padding:14px;margin-bottom:12px;background:var(--card);">'+
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">'+
          '<input type="radio" class="api-radio" name="api_index_radio" style="width:16px;height:16px;accent-color:var(--primary);cursor:pointer;">'+
          '<span class="api-config-num" style="font-weight:600;font-size:13.5px;"></span>'+
          '<span class="api-active-badge" style="font-size:11px;background:var(--primary);color:#fff;border-radius:10px;padding:1px 8px;display:none;">当前使用</span>'+
          '<button type="button" class="btn-rm btn-remove-api-config" style="margin-left:auto;" title="删除此接口"><i class="bi bi-trash"></i></button>'+
        '</div>'+
        '<div class="row g-2">'+
          '<div class="col-12 col-md-3"><label class="cfg-label">SDK</label>'+
            '<div style="position:relative;">'+
              '<select class="form-select api-sdk-select" style="appearance:none;-webkit-appearance:none;padding-right:28px;">'+
                '<option value="" disabled selected>请选择 SDK</option>'+
                '<option value="DusAPI">DusAPI</option>'+
                '<option value="OpenAI API 格式兼容接口">OpenAI API 格式兼容接口</option>'+
                '<option value="Dify">Dify</option>'+
                '<option value="Coze">Coze</option>'+
              '</select>'+
              '<i class="bi bi-chevron-down" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);pointer-events:none;font-size:11px;color:var(--muted);"></i>'+
            '</div></div>'+
          '<div class="col-12 col-md-3"><label class="cfg-label">模型</label>'+
            '<input type="text" class="form-control api-model-input" value="" placeholder="模型名称"></div>'+
          '<div class="col-12 col-md-6"><label class="cfg-label">Base URL</label>'+
            '<input type="text" class="form-control api-url-input" value="" placeholder="https://api.example.com"></div>'+
          '<div class="col-12"><label class="cfg-label">API Key</label>'+
            '<input type="text" class="form-control api-key-input" data-real-key="" placeholder="sk-..." autocomplete="off"></div>'+
          '<div class="col-12 col-md-6"><label class="cfg-label">备用接口</label>'+
            '<select class="form-select api-fallback-select" title="主接口失败时调用一次备用接口">'+
              '<option value="-1" selected>无</option>'+
            '</select></div>'+
        '</div>'+
      '</div>';
    $('#api_configs_container').append(html);
    renumberApiConfigs();
    syncApiConfigsList();
    refreshApiReferenceDropdowns();
    refreshApiFallbackOptions();
  });

  function renumberApiConfigs(){
    $('.api-config-item').each(function(i){
      $(this).find('.api-config-num').text('接口 '+(i+1));
    });
  }

  // ===== 群组专属接口：接口列表数据（Jinja2 注入，供动态添加群组行使用）=====
  var apiConfigsList = window.__API_CONFIGS__;
  function parseApiIndex(value){
    var index = parseInt(value, 10);
    return isNaN(index) ? -1 : index;
  }
  function escapeApiOptionText(value){
    return $('<div>').text(value == null ? '' : String(value)).html();
  }
  function syncApiConfigsList(){
    apiConfigsList = [];
    $('.api-config-item').each(function(){
      apiConfigsList.push({
        model: $(this).find('.api-model-input').val() || ''
      });
    });
  }
  function buildImageApiOpts(selectedIdx){
    var s = '';
    apiConfigsList.forEach(function(c,i){
      var sel=(i===selectedIdx)?' selected':'';
      s+='<option value="'+i+'"'+sel+'>接口'+(i+1)+': '+escapeApiOptionText((c.model||'').substring(0,20))+'</option>';
    });
    return s;
  }
  function refreshApiReferenceDropdowns(){
    syncApiConfigsList();
    $('.group-api-select').each(function(){
      var selectedIdx = parseApiIndex($(this).val());
      if(selectedIdx < 0 || selectedIdx >= apiConfigsList.length) selectedIdx = -1;
      $(this).html(buildGroupApiOpts(selectedIdx));
    });
    $('.chat-api-select').each(function(){
      var selectedIdx = parseApiIndex($(this).val());
      if(selectedIdx < 0 || selectedIdx >= apiConfigsList.length) selectedIdx = -1;
      $(this).html(buildChatApiOpts(selectedIdx));
    });
    $('#chat_image_recognition_api, #group_image_recognition_api').each(function(){
      var selectedIdx = parseApiIndex($(this).val());
      if(selectedIdx < 0 || selectedIdx >= apiConfigsList.length) selectedIdx = 0;
      $(this).html(buildImageApiOpts(selectedIdx));
    });
  }
  function refreshApiFallbackOptions(){
    var $items = $('.api-config-item');
    $items.each(function(i){
      var $select = $(this).find('.api-fallback-select');
      var selectedIdx = parseApiIndex($select.val());
      if(selectedIdx < 0 || selectedIdx >= $items.length || selectedIdx === i) selectedIdx = -1;
      var html = '<option value="-1"'+(selectedIdx===-1?' selected':'')+'>无</option>';
      $items.each(function(j){
        if(j === i) return;
        var model = $(this).find('.api-model-input').val() || '';
        html += '<option value="'+j+'"'+(selectedIdx===j?' selected':'')+'>接口'+(j+1)+': '+
          escapeApiOptionText(model.substring(0,20))+'</option>';
      });
      $select.html(html).val(String(selectedIdx));
    });
  }
  // ===== Prompt 列表数据（Jinja2 注入，供 prompt 下拉框和编辑器使用）=====
  var promptsList = window.__PROMPTS__;

  function buildGroupApiOpts(selectedIdx){
    var s = '<option value="-1"'+(selectedIdx===-1?' selected':'')+'>默认接口</option>';
    apiConfigsList.forEach(function(c,i){
      var sel=(i===selectedIdx)?' selected':'';
      s+='<option value="'+i+'"'+sel+'>接口'+(i+1)+': '+escapeApiOptionText((c.model||'').substring(0,20))+'</option>';
    });
    return s;
  }

  $('#btn-add-group-item').click(function(){
    $('#group_container').append(
      '<div class="list-item" style="flex-wrap:wrap;gap:6px;">'+
        '<input type="text" class="form-control" name="group" placeholder="群聊名称">'+
        '<select class="form-select group-prompt-select" style="width:145px;flex-shrink:0;" title="该群专属Prompt（空=使用全局Prompt）">'+
          buildPromptOpts('')+
        '</select>'+
        '<select class="form-select group-api-select" style="width:160px;flex-shrink:0;" title="该群调用的AI接口（选默认则跟随全局配置）">'+
          buildGroupApiOpts(-1)+
        '</select>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Sidebar Tab Switch =====
  function isMobileLayout(){
    return window.matchMedia('(max-width: 900px)').matches;
  }
  function getActiveTabId(){
    return $('.config-panel.active').attr('id') || '';
  }
  function isPageVisible(){
    return typeof document.hidden === 'boolean' ? !document.hidden : true;
  }
  function setMobileSidebar(open){
    $('body').toggleClass('mobile-nav-open', !!open);
    $('.sidebar').toggleClass('mobile-open', !!open);
    $('#mobileSidebarOverlay').toggleClass('active', !!open);
  }
  function activateTab(tabId){
    $('.sidebar .nav-link').removeClass('active');
    $('.sidebar .nav-link[data-tab="'+tabId+'"]').addClass('active');
    $('.config-panel').removeClass('active');
    $('#'+tabId).addClass('active');
    if(typeof syncStatusPolling === 'function'){
      syncStatusPolling(tabId === 'tab-status');
    }
    if(typeof syncSiverPanelPolling === 'function'){
      syncSiverPanelPolling(tabId === 'tab-siver-panel');
    }
    _saveUiState();   // 记住当前 tab，刷新后回到这里
  }
  $('#mobileMenuBtn').on('click', function(e){
    e.preventDefault();
    setMobileSidebar(true);
  });
  $('#mobileSidebarClose, #mobileSidebarOverlay').on('click', function(){
    setMobileSidebar(false);
  });
  $('.sidebar .nav-link').click(function(){
    var targetTabId = $(this).data('tab');
    activateTab(targetTabId);
    if(isMobileLayout()){
      setMobileSidebar(false);
    }
  });
  $(window).on('resize', function(){
    if(!isMobileLayout()){
      setMobileSidebar(false);
    }
    if(typeof syncMobileLogTitle === 'function'){
      syncMobileLogTitle();
    }
    if(typeof syncMobileRecentLogs === 'function'){
      syncMobileRecentLogs();
    }
    if(typeof syncLogViewport === 'function'){
      syncLogViewport();
    }
    if(typeof syncLogPolling === 'function'){
      syncLogPolling(false);
    }
    if(typeof syncStatusPolling === 'function'){
      syncStatusPolling(false);
    }
    if(typeof syncSiverPanelPolling === 'function'){
      syncSiverPanelPolling(false);
    }
  });

  // ===== Listen Mode Toggle =====
  $('#AllListen_switch').change(function(){
    var on=$(this).is(':checked');
    var $hint=$('#listenModeHint'), $icon=$hint.find('i'), $text=$('#listenModeText');
    if(on){
      $hint.css({background:'#FEF2F2',color:'#DC2626',border:'1px solid #FECACA'});
      $icon.attr('class','bi bi-shield-x');
      $text.text('当前为黑名单模式 — 以下用户的消息将被忽略');
    } else {
      $hint.css({background:'#F0FDF4',color:'#16A34A',border:'1px solid #BBF7D0'});
      $icon.attr('class','bi bi-shield-check');
      $text.text('当前为白名单模式 — 仅监听以下用户的消息');
    }
    _updateListenMode(on); // 同步全局 Prompt 行、per-user 下拉框、按钮文字等
  });

  // ===== Range Slider =====
  $('#group_welcome_random').on('input change',function(){
    var v=parseFloat($(this).val());
    $('#group_welcome_random_number').text(Math.round(v*100)+'%');
  });

  // ===== 发送延迟开关联动 =====
  $('#reply_delay_switch').on('change', function(){
    $('#reply-delay-settings').toggle(this.checked);
  });

  // ===== 回复轮数限制开关联动 =====
  $('#chat_max_round_switch').on('change', function(){
    $('#chat-max-round-settings').toggle(this.checked);
  });

  // ===== Remove List Item =====
  $(document).on('click','.btn-remove-item',function(){
    $(this).closest('.list-item, .keyword-item, .scheduled-msg-item, .scheduled-moments-item, .random-moments-item, .random-msg-item, .custom-forward-item').remove();
  });

  // ===== 选择本地文件（调后端弹系统文件选择框）=====
  // 远程访问时后端会拒绝（对话框只会弹在本机桌面上，远程用户点不到），
  // 所以这里必须把后端返回的提示如实弹出来；否则用户只看到按钮转一下就没了。
  // status==='cancel' 是用户自己取消了对话框，属正常操作，保持静默。
  // 填入目标：默认是"同一行里第一个 input/textarea"。
  // 一行里有多个输入框时（关键词行是"关键词" + "回复内容"），必须用 data-pick-target
  // 显式指明填哪个 —— 否则会落到"关键词"栏。选择器写相对本行的形式，
  // 因为这类行可以重复添加，不能用全局 id。
  // data-pick-kind="file"：消息类回复可选文档等任意文件；缺省 media 只列图片/视频
  // （朋友圈图片走 media，朋友圈不支持文档）。
  $(document).on('click','.btn-pick-img',function(){
    var $btn=$(this);
    var pickTarget=$btn.attr('data-pick-target');
    var pickKind=$btn.attr('data-pick-kind') || 'media';
    var $row=$btn.closest('.list-item, .keyword-item');
    var $input=pickTarget ? $row.find(pickTarget).first() : $row.find('input, textarea').first();
    $btn.prop('disabled',true).html('<i class="bi bi-hourglass-split"></i>');
    $.get('/pick_image_file', {kind: pickKind}, function(res){
      if(res && res.status==='success' && res.path){
        $input.val(res.path);
      } else if(res && res.status==='error'){
        svModal.alert(res.message || '无法打开文件选择框，请手动填写完整路径。', '选择本地文件失败');
      }
    }).fail(function(xhr){
      svModal.error('请求文件选择框失败：' + ((xhr && xhr.responseText) || (xhr && xhr.status) || '未知错误'));
    }).always(function(){
      $btn.prop('disabled',false).html('<i class="bi bi-folder2-open"></i>');
    });
  });

  // ===== Add List Item =====
  $(document).on('click','.btn-add[data-target]',function(){
    var target=$(this).data('target'), name=$(this).data('name');
    var placeholder=$(this).data('placeholder')||'';
    var pickBtn=$(this).data('imgpick')?'<button type="button" class="btn-pick-img" data-pick-kind="file" title="点击选择本地文件（图片/视频/文档等），自动填入路径"><i class="bi bi-folder2-open"></i></button>':'';
    var fieldHtml=$(this).data('multiline')
      ? '<textarea class="form-control" name="'+name+'" rows="2"></textarea>'
      : '<input type="text" class="form-control" name="'+name+'" placeholder="'+placeholder+'">';
    $(target).append(
      '<div class="list-item">'+
      fieldHtml+
      pickBtn+
      '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Prompt 辅助函数 =====
  function buildPromptOpts(selectedName) {
    var s = '<option value=""'+(selectedName===''||!selectedName?' selected':'')+'>默认（全局）</option>';
    promptsList.forEach(function(name){
      var sel = (name === selectedName) ? ' selected' : '';
      s += '<option value="'+name+'"'+sel+'>'+name+'</option>';
    });
    return s;
  }
  function buildChatApiOpts(selectedIdx) {
    var s = '<option value="-1"'+(selectedIdx===-1?' selected':'')+'>默认接口</option>';
    apiConfigsList.forEach(function(c,i){
      var sel=(i===selectedIdx)?' selected':'';
      s+='<option value="'+i+'"'+sel+'>接口'+(i+1)+': '+escapeApiOptionText((c.model||'').substring(0,20))+'</option>';
    });
    return s;
  }
  $(document).on('input change', '.api-model-input', function(){
    refreshApiReferenceDropdowns();
    refreshApiFallbackOptions();
  });
  refreshApiReferenceDropdowns();
  refreshApiFallbackOptions();
  function refreshAllPromptDropdowns() {
    ['#default_prompt_select', '.chat-prompt-select', '.group-prompt-select'].forEach(function(sel){
      $(sel).each(function(){
        var cur = $(this).val() || '';
        $(this).html(sel==='#default_prompt_select'
          ? promptsList.map(function(n){return '<option value="'+n+'"'+(n===cur?' selected':'')+'>'+n+'</option>';}).join('')
          : buildPromptOpts(cur)
        );
      });
    });
  }

  // ===== Prompt Editor =====
  var _promptCurrentOldName = '';

  // 初始化：选中第一个
  (function(){
    var $first = $('#prompt-list .prompt-list-item:first');
    if ($first.length) promptSelectItem($first[0]);
  })();

  function promptSelectItem(el) {
    var $el = $(el);
    $('.prompt-list-item').removeClass('active');
    $el.addClass('active');
    $('#prompt-name-input').val($el.data('name'));
    $('#prompt-content-input').val($el.data('content'));
    _promptCurrentOldName = $el.data('name');
  }
  // 列表点击
  $(document).on('click', '.prompt-list-item', function(){ promptSelectItem(this); });

  $('#btn-new-prompt').click(function(){
    $('.prompt-list-item').removeClass('active');
    $('#prompt-name-input').val('').focus();
    $('#prompt-content-input').val('');
    _promptCurrentOldName = '';
  });

  // 保存成功弹窗的正文：把后端 warnings 完整、按文本展示出来。
  // ⚠ 服务端数据（warnings 文本、里面的 Prompt 名称）一律 .text()：
  //   svModal 的 body 是富文本路径、只给常量 HTML 用；名称里带 < > & 也只是文本，
  //   不会被当成标签解析。这里只负责"如实展示"，不改任何引用 —— 引用要不要改、
  //   怎么改，仍由用户自己决定（后端也不改写 config.json）。
  function buildPromptSavedBody(warnings){
    var $body = $('<div>');
    $('<div>').text('Prompt 保存成功').appendTo($body);

    var list = (warnings && warnings.length) ? warnings : [];
    if (!list.length) { return $body; }        // 无警告 / 空数组：就是普通成功提示

    $('<div>')
      .css({marginTop:'10px', fontWeight:'600', color:'#B45309'})
      .text('以下 ' + list.length + ' 处需要你手动调整：')
      .appendTo($body);

    var $ul = $('<ul>').css({margin:'6px 0 0 18px', padding:'0'}).appendTo($body);
    list.forEach(function(w){
      $('<li>').css({marginBottom:'6px', lineHeight:'1.6'}).text(String(w)).appendTo($ul);
    });
    return $body;
  }

  $('#btn-save-prompt').click(function(){
    var name = $('#prompt-name-input').val().trim();
    var content = $('#prompt-content-input').val();
    if (!name) { svModal.error('Prompt 名称不能为空'); return; }
    var oldName = _promptCurrentOldName;
    $.ajax({
      url:'/save_prompt', type:'POST', contentType:'application/json',
      data: JSON.stringify({name:name, content:content, old_name:oldName}),
      success: function(res) {
        if (res.status !== 'success') { svModal.error('保存失败：'+(res.msg||'')); return; }
        // 更新 promptsList 和 DOM
        if (oldName && oldName !== name) {
          var oi = promptsList.indexOf(oldName);
          if (oi >= 0) promptsList.splice(oi, 1);
          $('#prompt-list .prompt-list-item[data-name="'+oldName+'"]').remove();
        }
        if (promptsList.indexOf(name) === -1) {
          promptsList.push(name);
          var $ni = $('<div class="prompt-list-item" data-name="'+name+'"></div>').text(name).attr('data-content', content);
          $('#prompt-list').append($ni);
          promptSelectItem($ni[0]);
        } else {
          var $exist = $('#prompt-list .prompt-list-item[data-name="'+name+'"]');
          $exist.attr('data-content', content).data('content', content);
          promptSelectItem($exist[0]);
        }
        _promptCurrentOldName = name;
        refreshAllPromptDropdowns();
        // 保存成功时如实展示后端的 warnings（重命名后仍被引用的旧名称、旧文件删除失败等），
        // 一条都不能漏；没有 warnings 时保持原来的普通成功提示。
        var warns = (res.warnings && res.warnings.length) ? res.warnings : [];
        var $savedBody = buildPromptSavedBody(warns);
        if (warns.length) { svModal.warnNode($savedBody, '保存成功，请留意'); }
        else { svModal.successNode($savedBody); }
      },
      error: function(xhr){ svModal.error('保存出错：'+xhr.responseText); }
    });
  });

  $('#btn-delete-prompt').click(function(){
    var name = _promptCurrentOldName;
    if (!name) { svModal.error('请先选中一个已保存的 Prompt'); return; }
    if (promptsList.length <= 1) { svModal.error('不允许删除最后一个 Prompt'); return; }
    svModal.confirm('确定删除 Prompt「'+name+'」？此操作不可恢复。', function(){
      $.ajax({
        url:'/delete_prompt', type:'POST', contentType:'application/json',
        data: JSON.stringify({name:name}),
        success: function(res) {
          if (res.status !== 'success') { svModal.error('删除失败：'+(res.msg||'')); return; }
          var oi = promptsList.indexOf(name);
          if (oi >= 0) promptsList.splice(oi, 1);
          $('#prompt-list .prompt-list-item[data-name="'+name+'"]').remove();
          var $first = $('#prompt-list .prompt-list-item:first');
          if ($first.length) promptSelectItem($first[0]);
          else { $('#prompt-name-input').val(''); $('#prompt-content-input').val(''); _promptCurrentOldName=''; }
          refreshAllPromptDropdowns();
          svModal.success('已删除');
        }
      });
    }, '删除确认', '确定删除', '取消');
  });

  // ===== Listen Tab：模式切换联动（扩展现有逻辑）=====
  function _updateListenMode(isGlobal) {
    $('#special-session-filter-row').toggle(isGlobal);
    if (isGlobal) {
      $('#global-prompt-row').show();
      $('#global-filter-mute-row').show();
      $('.listen-extra').hide();
      $('#listenListLabel').html('黑名单列表');
    } else {
      $('#global-prompt-row').hide();
      $('#global-filter-mute-row').hide();
      $('.listen-extra').show();
      $('#listenListLabel').html('监听列表 <span style="font-size:11px;color:var(--muted);font-weight:400;">（白名单模式：可为每个用户设置专属 Prompt、接口和回复上限）</span>');
    }
    $('#listenAddText').text(isGlobal ? '添加黑名单' : '添加监听');
  }
  // 页面加载时初始化
  _updateListenMode($('#AllListen_switch').is(':checked'));

  // ===== 新增监听条目 =====
  $('#btn-add-listen-item').click(function(){
    var isGlobal = $('#AllListen_switch').is(':checked');
    var extraHtml = isGlobal ? '' :
      '<div class="listen-extra" style="display:flex;gap:6px;flex-wrap:wrap;">'+
        '<select class="form-select chat-prompt-select" style="width:145px;flex-shrink:0;" title="专属Prompt">'+buildPromptOpts('')+'</select>'+
        '<select class="form-select chat-api-select" style="width:160px;flex-shrink:0;" title="专属接口">'+buildChatApiOpts(-1)+'</select>'+
        '<input type="number" class="form-control chat-max-round-input" min="1" max="99999" placeholder="全局上限" title="专属回复上限（留空=全局）" style="width:120px;flex-shrink:0;">'+
      '</div>';
    $('#listen_container').append(
      '<div class="list-item listen-item" style="flex-wrap:wrap;gap:6px;">'+
      '<input type="text" class="form-control" name="listen_list" placeholder="联系人昵称" style="min-width:120px;">'+
      extraHtml+
      '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Add Keyword =====
  $('#btn-add-keyword').click(function(){
    $('#keyword_container').append(
      '<div class="keyword-item">'+
      '<input type="text" class="form-control" name="keyword_key" placeholder="关键词">'+
      '<textarea class="form-control" name="keyword_value" placeholder="回复内容，或文件完整路径（图片/视频/文档等）"></textarea>'+
      '<button type="button" class="btn-pick-img" data-pick-target="textarea[name=keyword_value]" data-pick-kind="file" title="点击选择本地文件（图片/视频/文档等），自动填入路径"><i class="bi bi-folder2-open"></i></button>'+
      '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Custom Forward: 工具函数 =====
  function _fwdListItem(nameAttr, placeholder){
    return '<div class="list-item" style="margin-bottom:6px;">'+
      '<input type="text" class="form-control" name="'+nameAttr+'" placeholder="'+placeholder+'">'+
      '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>';
  }
  function _fwdSyncType($item){
    var t = $item.find('.fwd-type-select').val();
    $item.find('.fwd-keyword-block').toggle(t === 'keyword');
    $item.find('.fwd-sender-block').toggle(t === 'sender');
  }

  // 页面加载时初始化已有规则的条件显示
  $('.custom-forward-item').each(function(){ _fwdSyncType($(this)); });

  // 类型切换事件
  $(document).on('change', '.fwd-type-select', function(){
    _fwdSyncType($(this).closest('.custom-forward-item'));
  });

  // 添加来源
  $(document).on('click', '.btn-add-fwd-source', function(){
    $(this).prev('.fwd-source-list').append(_fwdListItem('fwd_source', '联系人昵称或群名'));
  });
  // 添加关键词
  $(document).on('click', '.btn-add-fwd-kw', function(){
    $(this).prev('.fwd-kw-list').append(_fwdListItem('fwd_keyword', '关键词'));
  });
  // 添加发送人
  $(document).on('click', '.btn-add-fwd-sender', function(){
    $(this).prev('.fwd-sender-list').append(_fwdListItem('fwd_sender', '发送人昵称'));
  });
  // 添加转发目标
  $(document).on('click', '.btn-add-fwd-target', function(){
    $(this).prev('.fwd-target-list').append(_fwdListItem('fwd_target', '联系人昵称或群名'));
  });

  // 添加新转发规则
  $('#btn-add-forward-rule').click(function(){
    var newId = Math.random().toString(36).substr(2,8);
    var html =
      '<div class="custom-forward-item" data-rule-id="'+newId+'">'+
        '<div class="d-flex align-items-center justify-content-between mb-3">'+
          '<span style="font-size:13px;font-weight:600;color:var(--primary);">转发规则</span>'+
          '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
        '</div>'+
        '<div class="mb-3">'+
          '<label class="cfg-label">监听来源 <span style="font-size:11px;color:var(--primary);font-weight:400;">（填入微信联系人昵称或群名，可添加多个）</span></label>'+
          '<div class="switch-row" style="margin-bottom:8px;">'+
            '<input class="form-check-input fwd-all-sources" type="checkbox" onchange="toggleFwdAllSources(this)">'+
            '<label style="font-size:13px;font-weight:600;cursor:pointer;">全部来源</label>'+
            '<span class="switch-desc">所有已监听的私聊和群组均作为来源，无需逐一填写</span>'+
          '</div>'+
          '<div class="fwd-manual-sources">'+
            '<div class="fwd-source-list"></div>'+
            '<button type="button" class="btn-add btn-add-fwd-source" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加来源</button>'+
          '</div>'+
        '</div>'+
        '<div class="mb-3">'+
          '<label class="cfg-label">转发类型 <span style="font-size:11px;color:var(--muted);font-weight:400;">（选择消息触发转发的条件类型）</span></label>'+
          '<select class="form-select fwd-type-select" style="max-width:260px;">'+
            '<option value="keyword">关键词转发</option>'+
            '<option value="all">无差别转发</option>'+
            '<option value="sender">固定发送人转发</option>'+
          '</select>'+
        '</div>'+
        '<div class="fwd-conditional-block fwd-keyword-block mb-3" style="display:block;">'+
          '<label class="cfg-label">关键词列表 <span style="font-size:11px;color:var(--primary);font-weight:400;">（消息内容包含任意一个关键词即触发转发）</span></label>'+
          '<div class="fwd-kw-list"></div>'+
          '<button type="button" class="btn-add btn-add-fwd-kw" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加关键词</button>'+
        '</div>'+
        '<div class="fwd-conditional-block fwd-sender-block mb-3">'+
          '<label class="cfg-label">发送人列表 <span style="font-size:11px;color:var(--primary);font-weight:400;">（填入微信昵称，仅该发送人的消息才触发转发）</span></label>'+
          '<div class="fwd-sender-list"></div>'+
          '<button type="button" class="btn-add btn-add-fwd-sender" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加发送人</button>'+
        '</div>'+
        '<div class="mb-1">'+
          '<label class="cfg-label">转发目标 <span style="font-size:11px;color:var(--primary);font-weight:400;">（填入联系人昵称或群名，可添加多个，每次转发间隔 1 秒）</span></label>'+
          '<div class="fwd-target-list"></div>'+
          '<button type="button" class="btn-add btn-add-fwd-target" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加转发目标</button>'+
          '<div class="switch-row" style="margin-top:10px;margin-bottom:0;">'+
            '<input class="form-check-input fwd-with-source" type="checkbox">'+
            '<label style="font-size:13px;">转发时附带来源信息 <span style="font-size:11px;color:var(--muted);font-weight:400;">（转发消息后自动补发一条"来源窗口：xxx，发送人：xxx"）</span></label>'+
          '</div>'+
        '</div>'+
      '</div>';
    $('#custom_forward_container').append(html);
  });

  // ===== Add Scheduled Msg in Task =====
  $(document).on('click','.btn-add-scheduled-target',function(){
    $(this).prev('.scheduled-target-list').append(
      '<div class="list-item" style="margin-bottom:6px;">'+
        '<input type="text" class="form-control" name="scheduled_target" placeholder="联系人或群名">'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  $(document).on('click','.btn-add-scheduled-msg',function(){
    $(this).prev('.scheduled-msg-list').append(
      '<div class="list-item">'+
      '<textarea class="form-control" name="scheduled_msg" rows="2" placeholder="文字内容 或 文件完整路径（图片/视频/文档等）"></textarea>'+
      '<button type="button" class="btn-pick-img" data-pick-kind="file" title="点击选择本地文件（图片/视频/文档等），自动填入路径"><i class="bi bi-folder2-open"></i></button>'+
      '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Weekday Button Toggle =====
  $(document).on('click','.weekday-btn',function(){
    $(this).toggleClass('active');
    $(this).next('.weekday-check').prop('checked',$(this).hasClass('active'));
  });

  // ===== Repeat Type Change =====
  $(document).on('change','.scheduled-repeat-type',function(){
    var item=$(this).closest('.scheduled-msg-item'), v=$(this).val();
    var $wd=item.find('.scheduled-weekdays');
    if(v==='weekly'){ $wd.css('display','flex'); } else { $wd.hide(); }
    item.find('.scheduled-monthly-days').toggle(v==='monthly');
    item.find('.scheduled-date').toggle(v==='once'||v==='custom');
  });

  // ===== Moments: 可见范围切换（显示/隐藏标签区域）=====
  $(document).on('change','.moments-privacy',function(){
    var wrap=$(this).closest('.scheduled-moments-item').find('.moments-tags-wrap');
    if($(this).val()==='public'){ wrap.hide(); } else { wrap.show(); }
  });

  // ===== Moments: 重复类型切换 =====
  $(document).on('change','.moments-repeat-type',function(){
    var item=$(this).closest('.scheduled-moments-item'), v=$(this).val();
    var $wd=item.find('.moments-weekdays');
    if(v==='weekly'){ $wd.css('display','flex'); } else { $wd.hide(); }
    item.find('.moments-monthly-days').toggle(v==='monthly');
    var $date=item.find('.moments-date');
    $date.toggle(v==='once'||v==='custom');
    // once用date输入框，custom用text（可填多个日期）
    var $di=item.find('.moments-date-input');
    if(v==='once'){ $di.attr('type','date'); $di.attr('placeholder','选择日期'); }
    else { $di.attr('type','text'); $di.attr('placeholder','如：2026-03-20（自定义多个用逗号分隔）'); }
  });

  // ===== Moments: 添加图片/视频路径 =====
  $(document).on('click','.btn-add-moments-image',function(){
    var list=$(this).prev('.moments-images-list');
    var count=list.find('input[name="moments_image"]').length;
    if(count>=9){ alert('最多只能添加9张图片'); return; }
    list.append(
      '<div class="list-item">'+
        '<input type="text" class="form-control" name="moments_image" placeholder="图片/视频完整路径，如 D:\\Images\\1.png">'+
        '<button type="button" class="btn-pick-img" title="点击选择本地图片/视频，自动填入路径"><i class="bi bi-folder2-open"></i></button>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Moments: 添加标签 =====
  $(document).on('click','.btn-add-moments-tag',function(){
    $(this).prev('.moments-tags-list').append(
      '<div class="list-item">'+
        '<input type="text" class="form-control" name="moments_tag" placeholder="标签名称">'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Moments: 添加朋友圈任务 =====
  var momentsIdCounter=Date.now()+1000000;
  $('#btn-add-moments-task').click(function(){
    momentsIdCounter++;
    var html=
    '<div class="scheduled-moments-item" data-moments-id="'+momentsIdCounter+'">'+
      '<div class="d-flex align-items-center justify-content-between mb-3">'+
        '<div class="switch-row" style="margin-bottom:0;flex:1">'+
          '<input class="form-check-input moments-enabled" type="checkbox" checked>'+
          '<label>启用此任务</label>'+
        '</div>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'+
      '<div class="mb-2"><label class="cfg-label">发送时间</label>'+
        '<input type="time" class="form-control" name="moments_time"></div>'+
      '<div class="mb-2"><label class="cfg-label">重复类型</label>'+
        '<select class="form-select moments-repeat-type">'+
          '<option value="daily">每天</option><option value="weekly">每周</option>'+
          '<option value="monthly">每月</option><option value="once">单次</option>'+
          '<option value="custom">自定义日期</option>'+
        '</select></div>'+
      '<div class="gap-2 mb-2 moments-weekdays" style="display:none">'+
        '<span class="weekday-btn" data-day="1">一</span><input type="checkbox" class="weekday-check d-none" value="1">'+
        '<span class="weekday-btn" data-day="2">二</span><input type="checkbox" class="weekday-check d-none" value="2">'+
        '<span class="weekday-btn" data-day="3">三</span><input type="checkbox" class="weekday-check d-none" value="3">'+
        '<span class="weekday-btn" data-day="4">四</span><input type="checkbox" class="weekday-check d-none" value="4">'+
        '<span class="weekday-btn" data-day="5">五</span><input type="checkbox" class="weekday-check d-none" value="5">'+
        '<span class="weekday-btn" data-day="6">六</span><input type="checkbox" class="weekday-check d-none" value="6">'+
        '<span class="weekday-btn" data-day="7">日</span><input type="checkbox" class="weekday-check d-none" value="7">'+
      '</div>'+
      '<div class="mb-2 moments-monthly-days" style="display:none">'+
        '<input type="text" class="form-control moments-monthly-val" placeholder="如：1,15 表示每月1号和15号"></div>'+
      '<div class="mb-2 moments-date" style="display:none">'+
        '<input type="date" class="form-control moments-date-input" placeholder="选择日期"></div>'+
      '<hr style="margin:12px 0;">'+
      '<div class="mb-2"><label class="cfg-label">朋友圈文字 <span style="font-size:11px;color:var(--muted);font-weight:400;">（选填，但文字和图片至少填一项）</span></label>'+
        '<textarea class="form-control moments-text" rows="4" placeholder="输入朋友圈文字内容，支持换行"></textarea></div>'+
      '<div class="mb-2"><label class="cfg-label">朋友圈图片 <span style="font-size:11px;color:var(--muted);font-weight:400;">（选填，最多9张，填本地图片绝对路径）</span></label>'+
        '<div class="cfg-hint" style="margin-bottom:8px;"><i class="bi bi-folder2-open" style="color:var(--primary);"></i> 每行填写一张图片的完整路径，如 <code>D:\\Images\\1.png</code></div>'+
        '<div class="moments-images-list">'+
          '<div class="list-item">'+
            '<input type="text" class="form-control" name="moments_image" placeholder="图片/视频完整路径，如 D:\\Images\\1.png">'+
            '<button type="button" class="btn-pick-img" title="点击选择本地图片/视频，自动填入路径"><i class="bi bi-folder2-open"></i></button>'+
            '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
          '</div>'+
        '</div>'+
        '<button type="button" class="btn-add btn-add-moments-image" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加图片/视频路径</button></div>'+
      '<div class="mb-2"><label class="cfg-label">可见范围</label>'+
        '<select class="form-select moments-privacy">'+
          '<option value="public">公开（所有人可见）</option>'+
          '<option value="whitelist">白名单（仅标签内的人可见）</option>'+
          '<option value="blacklist">黑名单（屏蔽标签内的人）</option>'+
        '</select></div>'+
      '<div class="mb-2 moments-tags-wrap" style="display:none">'+
        '<label class="cfg-label">标签列表 <span style="font-size:11px;color:var(--muted);font-weight:400;">（白名单：仅这些标签的人可见；黑名单：屏蔽这些标签的人）</span></label>'+
        '<div class="moments-tags-list"></div>'+
        '<button type="button" class="btn-add btn-add-moments-tag" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加标签</button>'+
      '</div>'+
    '</div>';
    $('#scheduled_moments_container').append(html);
  });

  // ===== Random Moments: 重复类型切换（显示/隐藏随机天数输入）=====
  $(document).on('change','.rm-repeat-type',function(){
    var $item=$(this).closest('.random-moments-item');
    var v=$(this).val();
    var $wrap=$item.find('.rm-days-wrap');
    if(v==='daily'){
      $wrap.hide();
    } else {
      $wrap.show();
      var maxDays=(v==='weekly'?7:31);
      var label=(v==='weekly')?'每周随机抽几天发布（1~7）':'每月随机抽几天发布（1~本月天数）';
      $wrap.find('.rm-days-label').html(label);
      $wrap.find('.rm-days-count').attr('max',maxDays);
      var cur=parseInt($wrap.find('.rm-days-count').val())||1;
      if(cur>maxDays) $wrap.find('.rm-days-count').val(maxDays);
    }
  });

  // ===== Random Moments: 可见范围切换 =====
  $(document).on('change','.rm-privacy',function(){
    var wrap=$(this).closest('.random-moments-item').find('.rm-tags-wrap');
    if($(this).val()==='public'){ wrap.hide(); } else { wrap.show(); }
  });

  // ===== Random Moments: 添加图片/视频路径 =====
  $(document).on('click','.btn-add-rm-image',function(){
    var list=$(this).prev('.rm-images-list');
    if(list.find('input[name="rm_image"]').length>=9){ alert('最多只能添加9张图片'); return; }
    list.append(
      '<div class="list-item">'+
        '<input type="text" class="form-control" name="rm_image" placeholder="图片/视频完整路径，如 D:\\Images\\1.png">'+
        '<button type="button" class="btn-pick-img" title="点击选择本地图片/视频"><i class="bi bi-folder2-open"></i></button>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Random Moments: 添加标签 =====
  $(document).on('click','.btn-add-rm-tag',function(){
    $(this).prev('.rm-tags-list').append(
      '<div class="list-item">'+
        '<input type="text" class="form-control" name="rm_tag" placeholder="标签名称">'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Random Moments: 添加任务 =====
  var rmIdCounter=Date.now()+2000000;
  $('#btn-add-random-moments').click(function(){
    rmIdCounter++;
    var html=
    '<div class="random-moments-item" data-rmid="'+rmIdCounter+'">'+
      '<div class="d-flex align-items-center justify-content-between mb-3">'+
        '<div class="switch-row" style="margin-bottom:0;flex:1">'+
          '<input class="form-check-input rm-enabled" type="checkbox" checked>'+
          '<label>启用此任务</label>'+
        '</div>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'+
      '<div class="row mb-2">'+
        '<div class="col-6"><label class="cfg-label">发布时间窗口 开始</label>'+
          '<input type="time" class="form-control rm-time-start" value="09:00"></div>'+
        '<div class="col-6"><label class="cfg-label">发布时间窗口 结束</label>'+
          '<input type="time" class="form-control rm-time-end" value="21:00"></div>'+
      '</div>'+
      '<div class="mb-2"><label class="cfg-label">重复类型</label>'+
        '<select class="form-select rm-repeat-type">'+
          '<option value="daily">每天</option>'+
          '<option value="weekly">每周</option>'+
          '<option value="monthly">每月</option>'+
        '</select></div>'+
      '<div class="mb-2 rm-days-wrap" style="display:none">'+
        '<label class="cfg-label rm-days-label">每周随机抽几天发布（1~7）</label>'+
        '<input type="number" class="form-control rm-days-count" min="1" max="7" value="1">'+
      '</div>'+
      '<hr style="margin:12px 0;">'+
      '<div class="mb-2"><label class="cfg-label">朋友圈文字 <span style="font-size:11px;color:var(--muted);font-weight:400;">（文字和图片至少填一项）</span></label>'+
        '<textarea class="form-control rm-text" rows="4" placeholder="输入朋友圈文字内容，支持换行"></textarea></div>'+
      '<div class="mb-2"><label class="cfg-label">朋友圈图片 <span style="font-size:11px;color:var(--muted);font-weight:400;">（选填，最多9张）</span></label>'+
        '<div class="rm-images-list"></div>'+
        '<button type="button" class="btn-add btn-add-rm-image" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加图片/视频路径</button></div>'+
      '<div class="mb-2"><label class="cfg-label">可见范围</label>'+
        '<select class="form-select rm-privacy">'+
          '<option value="public">公开（所有人可见）</option>'+
          '<option value="whitelist">白名单（仅标签内的人可见）</option>'+
          '<option value="blacklist">黑名单（屏蔽标签内的人）</option>'+
        '</select></div>'+
      '<div class="mb-2 rm-tags-wrap" style="display:none">'+
        '<label class="cfg-label">标签列表</label>'+
        '<div class="rm-tags-list"></div>'+
        '<button type="button" class="btn-add btn-add-rm-tag" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加标签</button>'+
      '</div>'+
    '</div>';
    $('#random_moments_container').append(html);
  });

  // ===== Add Scheduled Task =====
  var taskIdCounter=Date.now();
  $('#btn-add-scheduled-task').click(function(){
    taskIdCounter++;
    var html=
    '<div class="scheduled-msg-item" data-task-id="'+taskIdCounter+'">'+
      '<div class="d-flex align-items-center justify-content-between mb-3">'+
        '<div class="switch-row" style="margin-bottom:0;flex:1">'+
          '<input class="form-check-input scheduled-enabled" type="checkbox" checked>'+
          '<label>启用此任务</label>'+
        '</div>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'+
      '<div class="mb-2"><label class="cfg-label">发送目标 <span style="font-size:11px;color:var(--primary);font-weight:400;">（可添加多个，同一批消息将依次发给每个目标，用于群发）</span></label>'+
        '<div class="scheduled-target-list">'+
          '<div class="list-item" style="margin-bottom:6px;">'+
            '<input type="text" class="form-control" name="scheduled_target" placeholder="联系人或群名">'+
            '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
          '</div>'+
        '</div>'+
        '<button type="button" class="btn-add btn-add-scheduled-target" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加目标</button></div>'+
      '<div class="mb-2"><label class="cfg-label">发送时间</label>'+
        '<input type="time" class="form-control" name="scheduled_time"></div>'+
      '<div class="mb-2"><label class="cfg-label">重复类型</label>'+
        '<select class="form-select scheduled-repeat-type">'+
          '<option value="daily">每天</option><option value="weekly">每周</option>'+
          '<option value="monthly">每月</option><option value="once">单次</option>'+
          '<option value="custom">自定义日期</option>'+
        '</select></div>'+
      '<div class="gap-2 mb-2 scheduled-weekdays" style="display:none">'+
        '<span class="weekday-btn" data-day="1">一</span><input type="checkbox" class="weekday-check d-none" value="1">'+
        '<span class="weekday-btn" data-day="2">二</span><input type="checkbox" class="weekday-check d-none" value="2">'+
        '<span class="weekday-btn" data-day="3">三</span><input type="checkbox" class="weekday-check d-none" value="3">'+
        '<span class="weekday-btn" data-day="4">四</span><input type="checkbox" class="weekday-check d-none" value="4">'+
        '<span class="weekday-btn" data-day="5">五</span><input type="checkbox" class="weekday-check d-none" value="5">'+
        '<span class="weekday-btn" data-day="6">六</span><input type="checkbox" class="weekday-check d-none" value="6">'+
        '<span class="weekday-btn" data-day="7">日</span><input type="checkbox" class="weekday-check d-none" value="7">'+
      '</div>'+
      '<div class="mb-2 scheduled-monthly-days" style="display:none">'+
        '<input type="text" class="form-control monthly-days" placeholder="如：1,15 表示每月1号和15号"></div>'+
      '<div class="mb-2 scheduled-date" style="display:none">'+
        '<input type="date" class="form-control date-input"></div>'+
      '<label class="cfg-label">消息内容</label>'+
      '<div class="cfg-hint" style="margin-bottom:8px;"><i class="bi bi-image" style="color:var(--primary);"></i> 填写文字内容将发送文字；填写文件完整路径（图片/视频/文档/压缩包等，如 <code>C:\\文件\\报告.pdf</code>）将自动作为文件发送</div>'+
      '<div class="scheduled-msg-list">'+
        '<div class="list-item">'+
          '<textarea class="form-control" name="scheduled_msg" rows="2" placeholder="文字内容 或 文件完整路径（图片/视频/文档等）"></textarea>'+
          '<button type="button" class="btn-pick-img" data-pick-kind="file" title="点击选择本地文件（图片/视频/文档等），自动填入路径"><i class="bi bi-folder2-open"></i></button>'+
          '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
        '</div>'+
      '</div>'+
      '<button type="button" class="btn-add btn-add-scheduled-msg"><i class="bi bi-plus-circle"></i> 添加消息</button>'+
    '</div>';
    $('#scheduled_msg_container').append(html);
  });

  // ===== Random Msg: 重复类型切换（显示/隐藏随机天数输入）=====
  $(document).on('change','.rmsg-repeat-type',function(){
    var $item=$(this).closest('.random-msg-item');
    var v=$(this).val();
    var $wrap=$item.find('.rmsg-days-wrap');
    if(v==='daily'){
      $wrap.hide();
    } else {
      $wrap.show();
      $item.find('.rmsg-days-label').text(v==='monthly'?'每月随机抽几天发送':'每周随机抽几天发送');
      $item.find('.rmsg-days-count').attr('max',v==='monthly'?31:7);
    }
  });

  // ===== Random Msg: 添加目标 =====
  $(document).on('click','.btn-add-rmsg-target',function(){
    $(this).prev('.rmsg-target-list').append(
      '<div class="list-item" style="margin-bottom:6px;">'+
        '<input type="text" class="form-control" name="rmsg_target" placeholder="联系人或群名">'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Random Msg: 添加消息内容 =====
  $(document).on('click','.btn-add-rmsg-msg',function(){
    $(this).prev('.rmsg-msg-list').append(
      '<div class="list-item">'+
        '<textarea class="form-control" name="rmsg_msg" rows="2" placeholder="文字内容 或 文件完整路径（图片/视频/文档等）"></textarea>'+
        '<button type="button" class="btn-pick-img" data-pick-kind="file" title="点击选择本地文件（图片/视频/文档等），自动填入路径"><i class="bi bi-folder2-open"></i></button>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'
    );
  });

  // ===== Random Msg: 添加任务 =====
  var rmsgIdCounter=Date.now()+3000000;
  $('#btn-add-random-msg-task').click(function(){
    rmsgIdCounter++;
    var html=
    '<div class="random-msg-item" data-rmsgid="'+rmsgIdCounter+'">'+
      '<div class="d-flex align-items-center justify-content-between mb-3">'+
        '<div class="switch-row" style="margin-bottom:0;flex:1">'+
          '<input class="form-check-input rmsg-enabled" type="checkbox" checked>'+
          '<label>启用此任务</label>'+
        '</div>'+
        '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
      '</div>'+
      '<div class="mb-2"><label class="cfg-label">发送目标 <span style="font-size:11px;color:var(--primary);font-weight:400;">（可添加多个，同一批消息将依次发给每个目标，用于群发）</span></label>'+
        '<div class="rmsg-target-list">'+
          '<div class="list-item" style="margin-bottom:6px;">'+
            '<input type="text" class="form-control" name="rmsg_target" placeholder="联系人或群名">'+
            '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
          '</div>'+
        '</div>'+
        '<button type="button" class="btn-add btn-add-rmsg-target" style="margin-top:6px;"><i class="bi bi-plus-circle"></i> 添加目标</button></div>'+
      '<div class="row mb-2">'+
        '<div class="col-6"><label class="cfg-label">发送时间窗口 开始</label>'+
          '<input type="time" class="form-control rmsg-time-start" value="09:00"></div>'+
        '<div class="col-6"><label class="cfg-label">发送时间窗口 结束</label>'+
          '<input type="time" class="form-control rmsg-time-end" value="21:00"></div>'+
      '</div>'+
      '<div class="mb-2"><label class="cfg-label">重复类型</label>'+
        '<select class="form-select rmsg-repeat-type">'+
          '<option value="daily">每天</option>'+
          '<option value="weekly">每周</option>'+
          '<option value="monthly">每月</option>'+
        '</select></div>'+
      '<div class="mb-2 rmsg-days-wrap" style="display:none">'+
        '<label class="cfg-label rmsg-days-label">每周随机抽几天发送 <span class="cfg-hint" style="display:inline;margin-left:6px;">（不超过7）</span></label>'+
        '<input type="number" class="form-control rmsg-days-count" min="1" max="7" value="1"></div>'+
      '<label class="cfg-label">消息内容</label>'+
      '<div class="cfg-hint" style="margin-bottom:8px;"><i class="bi bi-image" style="color:var(--primary);"></i> 填写文字内容将发送文字；填写文件完整路径（图片/视频/文档/压缩包等，如 <code>C:\\文件\\报告.pdf</code>）将自动作为文件发送</div>'+
      '<div class="rmsg-msg-list">'+
        '<div class="list-item">'+
          '<textarea class="form-control" name="rmsg_msg" rows="2" placeholder="文字内容 或 文件完整路径（图片/视频/文档等）"></textarea>'+
          '<button type="button" class="btn-pick-img" data-pick-kind="file" title="点击选择本地文件（图片/视频/文档等），自动填入路径"><i class="bi bi-folder2-open"></i></button>'+
          '<button type="button" class="btn-rm btn-remove-item"><i class="bi bi-x-lg"></i></button>'+
        '</div>'+
      '</div>'+
      '<button type="button" class="btn-add btn-add-rmsg-msg"><i class="bi bi-plus-circle"></i> 添加消息</button>'+
    '</div>';
    $('#random_msg_container').append(html);
  });

  // ===== Save Config =====
  function saveConfig(callback){
    // --- ① 接口列表与当前接口索引（含 API Key 遮罩保护）---
    var api_configs=[];
    var api_index=0;
    var _keyUpdates=[];
    var api_config_count=$('.api-config-item').length;
    $('.api-config-item').each(function(i){
      if($(this).find('.api-radio').is(':checked')) api_index=i;
      var $k=$(this).find('.api-key-input');
      var typedKey=$k.val(), maskedKey=$k.data('masked')||'', realKey=$k.data('real-key')||'';
      // 若显示的是遮罩值或为空，保留原真实 Key；否则使用用户输入的新 Key
      var keyToSave=(typedKey===maskedKey||typedKey==='')?realKey:typedKey;
      _keyUpdates.push({$el:$k, key:keyToSave});
      var sdk=$(this).find('.api-sdk-select').val()||'';
      var model=$(this).find('.api-model-input').val();
      var url=$(this).find('.api-url-input').val();
      var fallbackApiIndex=parseApiIndex($(this).find('.api-fallback-select').val());
      if(fallbackApiIndex < 0 || fallbackApiIndex >= api_config_count || fallbackApiIndex === i) {
        fallbackApiIndex=-1;
      }
      api_configs.push({
        sdk:sdk,
        model:model,
        url:url,
        key:keyToSave,
        fallback_api_index:fallbackApiIndex
      });
    });
    // --- ② 简单字段：一行一个手写映射，新增字段加在这里 ---
    var configData={
      api_configs:api_configs,
      api_index:api_index,
      AllListen_switch:$('#AllListen_switch').is(':checked'),
      AllListen_filter_mute:$('#AllListen_filter_mute').is(':checked'),
      chat_listen_only:$('#chat_listen_only').is(':checked'),
      group_switch:$('#group_switch').is(':checked'),
      group_listen_only:$('#group_listen_only').is(':checked'),
      group_reply_at:$('#group_reply_at').is(':checked'),
      group_reply_at_msg:$('#group_reply_at_msg').is(':checked'),
      group_reply_quote:$('#group_reply_quote').is(':checked'),
      group_welcome:$('#group_welcome').is(':checked'),
      new_friend_switch:$('#new_friend_switch').is(':checked'),
      new_friend_reply_switch:$('#new_friend_reply_switch').is(':checked'),
      new_friend_check_min:parseInt($('#new_friend_check_min').val())||60,
      new_friend_check_max:parseInt($('#new_friend_check_max').val())||300,
      new_friend_remark_use_nickname:$('#new_friend_remark_use_nickname').is(':checked'),
      new_friend_remark_prefix:$('#new_friend_remark_prefix').val(),
      new_friend_remark_prefix_timestamp:$('#new_friend_remark_prefix_timestamp').is(':checked'),
      new_friend_remark_suffix:$('#new_friend_remark_suffix').val(),
      new_friend_remark_suffix_timestamp:$('#new_friend_remark_suffix_timestamp').is(':checked'),
      new_friend_tags:$('[name="new_friend_tags"]').map(function(){return $(this).val();}).get().filter(s=>s.trim()!==''),
      chat_keyword_switch:$('#chat_keyword_switch').is(':checked'),
      group_keyword_switch:$('#group_keyword_switch').is(':checked'),
      group_keyword_at_only:$('#group_keyword_at_only').is(':checked'),
      keyword_reply_quote:$('#keyword_reply_quote').is(':checked'),
      group_keyword_reply_at_msg:$('#group_keyword_reply_at_msg').is(':checked'),
      admin:$('#admin').val(),
      group_welcome_msg:$('#group_welcome_msg').summernote('code'),
      default_prompt:$('#default_prompt_select').val()||'默认',
      listen_list:[], special_session_name:[], group:[], group_api_map:{}, group_prompt_map:{}, new_friend_msg:[],
      chat_prompt_map:{}, chat_api_map:{}, chat_max_round_map:{},
      group_welcome_random:parseFloat($('#group_welcome_random').val()),
      keyword_dict:{},
      scheduled_msg_switch:$('#scheduled_msg_switch').is(':checked'),
      scheduled_msg_list:[],
      random_msg_switch:$('#random_msg_switch').is(':checked'),
      random_msg_list:[],
      scheduled_moments_switch:$('#scheduled_moments_switch').is(':checked'),
      scheduled_moments_list:[],
      random_moments_switch:$('#random_moments_switch').is(':checked'),
      random_moments_list:[],
      moments_like_switch:$('#moments_like_switch').is(':checked'),
      moments_like_min:Math.max(1,Math.min(1440,parseInt($('#moments_like_min').val())||60)),
      moments_like_max:Math.max(1,Math.min(1440,parseInt($('#moments_like_max').val())||120)),
      everyday_start_stop_bot_switch:$('#everyday_start_stop_bot_switch').is(':checked'),
      everyday_start_bot_time:$('#everyday_start_bot_time').val(),
      everyday_stop_bot_time:$('#everyday_stop_bot_time').val(),
      memory_switch:$('#memory_switch').is(':checked'),
      memory_max_count:parseInt($('#memory_max_count').val())||3000,
      memory_context_count:parseInt($('#memory_context_count').val())||1000,
      reply_delay_switch:$('#reply_delay_switch').is(':checked'),
      reply_delay_min:Math.max(1,parseInt($('#reply_delay_min').val())||1),
      reply_delay_max:Math.max(1,parseInt($('#reply_delay_max').val())||5),
      chat_image_recognition_switch:$('#chat_image_recognition_switch').is(':checked'),
      chat_image_recognition_api:parseInt($('#chat_image_recognition_api').val())||0,
      group_image_recognition_switch:$('#group_image_recognition_switch').is(':checked'),
      group_image_recognition_api:parseInt($('#group_image_recognition_api').val())||0,
      api_error_reply:$('#api_error_reply').val().trim()||'在忙，我稍后回复您',
      api_error_reply_once:$('#api_error_reply_once').is(':checked'),
      clean_ai_reply_switch:$('#clean_ai_reply_switch').is(':checked'),
      chat_max_round_switch:$('#chat_max_round_switch').is(':checked'),
      chat_max_round_default:Math.max(1,Math.min(99999,parseInt($('#chat_max_round_default').val())||99)),
      chat_max_round_reset_days:Math.max(0,Math.min(365,parseInt($('#chat_max_round_reset_days').val())||0)),
      chat_max_round_reply:$('#chat_max_round_reply').val().trim(),
      chat_max_round_reply_once:$('#chat_max_round_reply_once').is(':checked'),
      chat_split_reply_switch:$('#chat_split_reply_switch').is(':checked'),
      chat_split_max_chars:Math.max(1,parseInt($('#chat_split_max_chars').val())||100),
      chat_split_max_count:Math.max(1,parseInt($('#chat_split_max_count').val())||4),
      group_split_reply_switch:$('#group_split_reply_switch').is(':checked'),
      group_split_max_chars:Math.max(1,parseInt($('#group_split_max_chars').val())||100),
      group_split_max_count:Math.max(1,parseInt($('#group_split_max_count').val())||4),
      merge_reply_switch:$('#merge_reply_switch').is(':checked'),
      merge_reply_window:Math.max(1,Math.min(300,parseInt($('#merge_reply_window').val())||5)),
      merge_reply_max_count:Math.max(1,Math.min(100,parseInt($('#merge_reply_max_count').val())||10)),
      siver_panel_enabled:$('#siver_panel_enabled').is(':checked'),
      siver_panel_activation_code:$('#siver_panel_activation_code').val().trim(),
      siver_panel_slug:normalizeSiverPanelSlug($('#siver_panel_slug').val()),
      custom_forward_switch:$('#custom_forward_switch').is(':checked'),
      custom_forward_list:[]
    };
    // --- ③ 私聊监听列表 + 白名单专属 Prompt / 接口 / 回复上限 ---
    $('#listen_container .listen-item').each(function(){
      var uname = $(this).find('input[name="listen_list"]').val().trim();
      if (!uname) return;
      configData.listen_list.push(uname);
      if (!$('#AllListen_switch').is(':checked')) {
        var pv = $(this).find('.chat-prompt-select').val();
        if (pv) configData.chat_prompt_map[uname] = pv;
        var av = parseInt($(this).find('.chat-api-select').val());
        if (!isNaN(av) && av >= 0) configData.chat_api_map[uname] = av;
        var rv = parseInt($(this).find('.chat-max-round-input').val());
        if (!isNaN(rv) && rv >= 1) configData.chat_max_round_map[uname] = Math.min(99999, rv);
      }
    });
    // --- ④ 全局监听的特殊会话过滤名单（自动去重）---
    $('#special_session_name_container input[name="special_session_name"]').each(function(){
      var sessionName = $(this).val().trim();
      if (sessionName && configData.special_session_name.indexOf(sessionName) === -1) {
        configData.special_session_name.push(sessionName);
      }
    });
    // --- ⑤ 群组列表 + 专属接口 / Prompt 映射 ---
    $('#group_container .list-item').each(function(){
      var name=$(this).find('input[name="group"]').val().trim();
      if(!name) return;
      configData.group.push(name);
      var idx=parseInt($(this).find('.group-api-select').val());
      if(!isNaN(idx) && idx>=0){ configData.group_api_map[name]=idx; }
      var gpv=$(this).find('.group-prompt-select').val();
      if(gpv){ configData.group_prompt_map[name]=gpv; }
    });
    // --- ⑥ 新好友招呼消息 + 关键词字典 ---
    $('[name="new_friend_msg"]').each(function(){ if($(this).val()) configData.new_friend_msg.push($(this).val()); });
    var keys=$('input[name="keyword_key"]'), vals=$('textarea[name="keyword_value"]');
    keys.each(function(i){ var k=$(this).val(); if(k) configData.keyword_dict[k]=vals.eq(i).val(); });
    // --- ⑦ 定时消息任务列表 ---
    $('.scheduled-msg-item').each(function(){
      var $t=$(this), msgs=[];
      $t.find('[name="scheduled_msg"]').each(function(){ if($(this).val()) msgs.push($(this).val()); });
      var weekdays=[];
      $t.find('.weekday-check:checked').each(function(){ weekdays.push(parseInt($(this).val())); });
      configData.scheduled_msg_list.push({
        id:$t.data('task-id'),
        enabled:$t.find('.scheduled-enabled').is(':checked'),
        targets:(function(){ var a=[]; $t.find('input[name="scheduled_target"]').each(function(){ if($(this).val().trim()) a.push($(this).val().trim()); }); return a; })(),
        time:$t.find('input[name="scheduled_time"]').val(),
        repeat_type:$t.find('.scheduled-repeat-type').val(),
        weekdays:weekdays,
        dates:(function(){
          var rt=$t.find('.scheduled-repeat-type').val();
          if(rt==='monthly'){
            var raw=$t.find('.monthly-days').val()||'';
            return raw?raw.split(',').map(function(s){return parseInt(s.trim())}).filter(function(n){return !isNaN(n)}):[];
          } else if(rt==='once'||rt==='custom'){
            var raw=$t.find('.date-input').val()||'';
            return raw?raw.split(',').map(function(s){return s.trim()}).filter(function(s){return s}):[];
          }
          return [];
        })(),
        msgs:msgs
      });
    });
    // --- ⑧ 随机定时消息任务列表 ---
    $('.random-msg-item').each(function(){
      var $r=$(this), msgs=[];
      $r.find('[name="rmsg_msg"]').each(function(){ if($(this).val()) msgs.push($(this).val()); });
      var repeatType=$r.find('.rmsg-repeat-type').val();
      var daysCount=parseInt($r.find('.rmsg-days-count').val())||1;
      var maxDays=(repeatType==='weekly'?7:31);
      daysCount=Math.max(1,Math.min(maxDays,daysCount));
      configData.random_msg_list.push({
        id:$r.data('rmsgid'),
        enabled:$r.find('.rmsg-enabled').is(':checked'),
        targets:(function(){ var a=[]; $r.find('input[name="rmsg_target"]').each(function(){ if($(this).val().trim()) a.push($(this).val().trim()); }); return a; })(),
        time_start:$r.find('.rmsg-time-start').val()||'09:00',
        time_end:$r.find('.rmsg-time-end').val()||'21:00',
        repeat_type:repeatType,
        random_days_count:daysCount,
        msgs:msgs
      });
    });
    // --- ⑨ 随机定时朋友圈任务列表 ---
    $('.random-moments-item').each(function(){
      var $r=$(this), images=[], tags=[];
      $r.find('input[name="rm_image"]').each(function(){ if($(this).val().trim()) images.push($(this).val().trim()); });
      $r.find('input[name="rm_tag"]').each(function(){ if($(this).val().trim()) tags.push($(this).val().trim()); });
      var repeatType=$r.find('.rm-repeat-type').val();
      var daysCount=parseInt($r.find('.rm-days-count').val())||1;
      var maxDays=(repeatType==='weekly'?7:31);
      daysCount=Math.max(1,Math.min(maxDays,daysCount));
      configData.random_moments_list.push({
        id:$r.data('rmid'),
        enabled:$r.find('.rm-enabled').is(':checked'),
        time_start:$r.find('.rm-time-start').val()||'09:00',
        time_end:$r.find('.rm-time-end').val()||'21:00',
        repeat_type:repeatType,
        random_days_count:daysCount,
        text:$r.find('.rm-text').val(),
        images:images,
        privacy:$r.find('.rm-privacy').val(),
        tags:tags
      });
    });
    // --- ⑩ 定时朋友圈任务列表 ---
    $('.scheduled-moments-item').each(function(){
      var $m=$(this), images=[], tags=[], weekdays=[];
      $m.find('input[name="moments_image"]').each(function(){ if($(this).val().trim()) images.push($(this).val().trim()); });
      $m.find('input[name="moments_tag"]').each(function(){ if($(this).val().trim()) tags.push($(this).val().trim()); });
      $m.find('.weekday-check:checked').each(function(){ weekdays.push(parseInt($(this).val())); });
      configData.scheduled_moments_list.push({
        id:$m.data('moments-id'),
        enabled:$m.find('.moments-enabled').is(':checked'),
        time:$m.find('input[name="moments_time"]').val(),
        repeat_type:$m.find('.moments-repeat-type').val(),
        weekdays:weekdays,
        dates:(function(){
          var rt=$m.find('.moments-repeat-type').val();
          if(rt==='monthly'){
            var raw=$m.find('.moments-monthly-val').val()||'';
            return raw?raw.split(',').map(function(s){return parseInt(s.trim())}).filter(function(n){return !isNaN(n)}):[];
          } else if(rt==='once'||rt==='custom'){
            var raw=$m.find('.moments-date-input').val()||'';
            return raw?raw.split(',').map(function(s){return s.trim()}).filter(function(s){return s}):[];
          }
          return [];
        })(),
        text:$m.find('.moments-text').val(),
        images:images,
        privacy:$m.find('.moments-privacy').val(),
        tags:tags
      });
    });
    // --- ⑪ 自定义转发规则列表 ---
    $('.custom-forward-item').each(function(){
      var $r=$(this), sources=[], keywords=[], senders=[], targets=[];
      $r.find('input[name="fwd_source"]').each(function(){ if($(this).val().trim()) sources.push($(this).val().trim()); });
      $r.find('input[name="fwd_keyword"]').each(function(){ if($(this).val().trim()) keywords.push($(this).val().trim()); });
      $r.find('input[name="fwd_sender"]').each(function(){ if($(this).val().trim()) senders.push($(this).val().trim()); });
      $r.find('input[name="fwd_target"]').each(function(){ if($(this).val().trim()) targets.push($(this).val().trim()); });
      configData.custom_forward_list.push({
        id: $r.data('rule-id'),
        all_sources: $r.find('.fwd-all-sources').is(':checked'),
        sources: sources,
        type: $r.find('.fwd-type-select').val(),
        keywords: keywords,
        senders: senders,
        targets: targets,
        forward_with_source: $r.find('.fwd-with-source').is(':checked')
      });
    });
    // --- ⑫ 提交（带上页面加载时的配置版本号，冲突时不静默覆盖）---
    configData._rev = window.__CONFIG_REV__ || '';
    $.ajax({
      url:'/save_config', type:'POST', contentType:'application/json',
      data:JSON.stringify(configData),
      success:function(res){ if(res.status==='success'){
        if(res.rev) window.__CONFIG_REV__ = res.rev;   // 同步版本号，后续保存才不会误判冲突
        // 保存成功后对每个 key 字段重新显示遮罩
        $.each(_keyUpdates,function(i,u){
          var m=maskApiKey(u.key);
          u.$el.val(m).attr('data-masked',m).attr('data-real-key',u.key).data('masked',m).data('real-key',u.key).attr('placeholder','sk-...');
        });
        if(callback) callback(res); else _showSaveResult(res);
      } else {svModal.error('保存失败: '+(res.message||''));} },
      error:function(xhr){
        var r = xhr.responseJSON || {};
        if(r.status === 'conflict'){ _handleConfigConflict(r, callback); return; }
        svModal.error('保存配置出错: '+(r.message || xhr.responseText));
      }
    });
  }

  // ===== 保存结果提示：区分「已应用 / 部分生效需重启 / 需重启 / 机器人未运行 / 应用失败」=====
  // 生效约定由后端 config_apply.py 统一给出，前端只负责如实展示，不自己判断哪些字段要重启。
  function _showSaveResult(res){
    var notes = [];
    if(res.apply_state === 'failed'){
      notes.push('⚠ ' + (res.apply_message || '配置已保存，但推送给运行中的机器人失败'));
    } else if(res.apply_state === 'not_running'){
      notes.push(res.apply_message || '机器人当前未运行，配置将在下次启动时生效');
    } else if(res.apply_state === 'partial' || res.apply_state === 'needs_restart'){
      notes.push(res.apply_message || '部分配置需重启后才生效');
    }
    if(res.needs_restart){
      notes.push('需重启才生效：' + (res.restart_hint || '监听名单 / 群列表 / 定时任务')
        + '<br>请点顶部「重启载入新配置」（重启会先等机器人真正停止，再载入新配置启动）');
    }
    if(notes.length === 0){ svModal.success('配置保存成功'); return; }
    svModal.alert('配置保存成功。<br><br>' + notes.join('<br><br>'), '配置保存成功');
  }

  // ===== 配置版本冲突：保留用户正在编辑的内容，不静默覆盖 =====
  function _handleConfigConflict(r, callback){
    var latestRev = r.rev || '';
    svModal.conflict(
      '页面打开后，配置在别处被修改过（另一个标签页 / 微信命令 / 远程面板），本次保存未生效。'
      + '<br><br><b>你页面上的编辑内容仍然保留，没有丢失。</b><br><br>'
      + '· <b>重新加载</b>：查看最新配置，放弃当前页面上的未保存修改<br>'
      + '· <b>强制覆盖</b>：用当前页面内容覆盖，丢弃别处的改动',
      function(){ location.reload(); },
      function(){ window.__CONFIG_REV__ = latestRev; saveConfig(callback); }
    );
  }

  // ===== Button Handlers =====
  $('#btnSave').click(function(){ saveConfig(); });
  $('#btnLoad').click(function(){
    svModal.confirm(
      '将放弃当前页面上未保存的修改，并从磁盘重新加载配置。'
      + '<br><br>页面会刷新，但会停留在当前栏目（位置和日志面板状态也会保留）。确定？',
      function(){ location.reload(); }, '放弃修改并重新加载', '确定重新加载', '取消');
  });
  $('#siver_panel_slug').on('input', function(){
    this.value = normalizeSiverPanelSlug(this.value).replace(/[^a-z0-9-]/g, '');
    updateSiverPanelUrlPreview();
  });
  $('#siver_panel_enabled').on('change', function(){
    updateSiverPanelUrlPreview();
    if(!this.checked){
      $.post('/api/siver-panel/disconnect').always(function(){ refreshSiverPanelStatus(); });
    } else {
      renderSiverPanelStatus({
        state:'idle',
        enabled:true,
        slug:normalizeSiverPanelSlug($('#siver_panel_slug').val()),
        last_message:'已开启远程访问服务，保存后可手动连接，或等待面板下次启动自动连接。'
      });
    }
  });
  $('#btn-siver-panel-connect').on('click', function(){ connectSiverPanel(); });
  updateSiverPanelUrlPreview();

  function _doStartBot(){
    $.post('/start_bot', function(res){
      if(res.status === 'success') svModal.success(res.message||'启动命令已发送', '已发送');
      else svModal.error(res.message||'启动失败');
    }).fail(function(xhr){ svModal.error('启动失败: '+xhr.responseText); });
  }

  $('#btnStart').click(function(){
    saveConfig(function(){
      var newVer = $('#update-new-ver').text();
      if(_activateStatus === false && _hasUpdate){
        // 两个问题都有：先提示更新，继续后再提示激活
        svModal.warnUpdate(newVer, function(){
          svModal.warnActivate(function(){ _doStartBot(); });
        });
      } else if(_hasUpdate){
        svModal.warnUpdate(newVer, function(){ _doStartBot(); });
      } else if(_activateStatus === false){
        svModal.warnActivate(function(){ _doStartBot(); });
      } else {
        _doStartBot();
      }
    });
  });
  $('#btnStop').click(function(){
    svModal.confirm('确定要停止机器人吗？', function(){
      $.post('/stop_bot', function(res){
        if(res.status === 'success') svModal.success(res.message||'机器人已停止', '已停止');
        else svModal.error(res.message||'停止失败');
      }).fail(function(xhr){ svModal.error('停止失败: '+xhr.responseText); });
    }, '停止机器人', '确定停止', '取消');
  });

  // 单次状态请求的超时。⚠ 与"停止确认总预算"（30 秒）是两件事：
  //   预算是「多久之内必须确认停住」，这里是「这一发请求多久算没答上」。
  // 每一次状态请求（含重启前的那次检查、以及等待期间的每一轮轮询）都走这个超时，
  // 保证成功/失败两条路都一定会回调 —— 不会出现"请求挂住 → 按钮永久禁用"。
  var STATUS_REQUEST_TIMEOUT_MS = 8000;
  var _statusXhr = null;      // 最近一次状态请求；流程收口时用它中止在途请求

  function fetchBotStatus(cb){
    _statusXhr = $.ajax({url: '/get_status', type: 'GET', dataType: 'json', timeout: STATUS_REQUEST_TIMEOUT_MS})
      .done(function(res){ cb(null, (res && res.status === 'success') ? res.data : null); })
      .fail(function(xhr, textStatus){
        cb({
          message: textStatus === 'timeout'
            ? ('读取运行状态超时（' + STATUS_REQUEST_TIMEOUT_MS + 'ms）')
            : ('读取运行状态失败：' + ((xhr && xhr.responseText) || textStatus || '未知错误')),
          timeout: textStatus === 'timeout'
        });
      });
  }

  // 流程结束（成功/失败/超时/被顶替）时中止还挂着的那一发：
  // 连接不必一直吊着，也少一个"流程已收口才回来的迟到回调"。
  function abortBotStatusRequest(){
    var xhr = _statusXhr;
    _statusXhr = null;
    if (xhr && xhr.readyState !== 4) {
      try { xhr.abort(); } catch (e) { /* 已经结束的请求忽略 */ }
    }
  }

  // 每点一次 +1：回调里先核对是不是自己这一轮，
  // 上一轮的迟到回调不得改到新一轮的界面。
  var _restartSeq = 0;

  $('#btnRestart').click(function(){
    var $btn = $(this);
    var runId = ++_restartSeq;
    function isCurrentRun(){ return runId === _restartSeq; }
    var defaultHtml = '<i class="bi bi-arrow-repeat"></i> 重启载入新配置';
    function resetButton(){
      $btn.prop('disabled', false).html(defaultHtml);
    }
    function postJson(url, cb){
      // 带超时：StopListening 卡住时后台可能长时间不返回，不能让按钮一直转圈。
      // ⚠ 这是「停止/启动请求自身」的超时，与停止确认的总预算（30 秒）互相独立：
      //   预算只约束"等它真的停下来"，不因为这个请求超时而顺延或重置。
      $.ajax({url: url, type: 'POST', timeout: 45000})
        .done(function(res){ cb(null, res); })
        .fail(function(xhr, textStatus){
          // 409 也带 JSON 响应体（含真实状态与原因），优先用它而不是裸文本
          var body = xhr.responseJSON || null;
          if(body){ cb(null, body); }
          else if(textStatus === 'timeout'){
            cb({message: '请求超时（' + url + '）：后台可能仍在停止中，请稍后查看运行日志/状态'});
          }
          else { cb({message: xhr.responseText || ('请求失败: ' + url)}); }
        });
    }
    saveConfig(function(){
      if(!isCurrentRun()){ return; }
      $btn.prop('disabled', true).html('<i class="bi bi-search"></i> 检查状态...');
      fetchBotStatus(function(err, data){
        if(!isCurrentRun()){ return; }
        if(err){
          svModal.error('检查运行状态失败：' + (err.message || '未知错误'));
          resetButton();
          return;
        }
        // 门禁用"真实状态"而不是 bot_running：停止中（stopping）时 bot_running 已经是
        // false，但那并不是"没在运行、无需重启"——此时点启动会被拒绝，必须先等它停完。
        var state = data ? BotRestart.stateOf(data) : 'unknown';
        if(state === 'stopped'){
          svModal.alert('配置已保存。机器人当前未运行，无需重启；如需载入新配置，请点击“启动机器人”。', '机器人未运行');
          resetButton();
          return;
        }
        // 停止 → 轮询 /get_status 直到确认真实停止 → 启动。
        // 不再"固定等 4 秒"：4 秒不能当作后台已经停了的保证。
        BotRestart.runRestart({
          timeoutMs: 30000,
          intervalMs: 800,
          requestTimeoutMs: STATUS_REQUEST_TIMEOUT_MS,
          onStage: function(stage){
            if(!isCurrentRun()){ return; }
            if(stage === 'stop') $btn.html('<i class="bi bi-stop-fill"></i> 正在停止...');
            else if(stage === 'wait') $btn.html('<i class="bi bi-hourglass-split"></i> 等待停止...');
            else if(stage === 'start') $btn.html('<i class="bi bi-play-fill"></i> 正在启动...');
          },
          onTick: function(info){
            if(!isCurrentRun()){ return; }
            $btn.html('<i class="bi bi-hourglass-split"></i> 等待停止(' + Math.ceil(info.elapsedMs / 1000) + 's)...');
          },
          postStop: function(cb){ postJson('/stop_bot', cb); },
          postStart: function(cb){ postJson('/start_bot', cb); },
          fetchStatus: fetchBotStatus,
          onAbort: abortBotStatusRequest
        }).then(function(result){
          if(!isCurrentRun()){ return; }
          svModal.success((result.start && result.start.message) || '机器人已重启并载入新配置', '重启成功');
          resetButton();
        }).catch(function(err){
          // 已被新一轮重启接管（或被新流程顶替）：界面归新流程管，这里一律不动
          if(!isCurrentRun()){ return; }
          if(err && err.cancelled){ return; }
          svModal.error(BotRestart.describeFailure(err), '重启未完成');
          resetButton();
        });
      });
    });
  });

  // ===== Log Panel =====
  var $logPanel=$('#logPanel'), $logBody=$('#logBody');
  var currentFilter='ALL';

  function syncMobileLogTitle(){
    if(!window.matchMedia('(max-width: 900px)').matches) return;
    $('.log-title-sub').text($logPanel.hasClass('expanded') ? '查看全部' : '最近两条');
  }

  function syncMobileRecentLogs(){
    var $preview = $('#mobileLogPreview');
    if(!window.matchMedia('(max-width: 900px)').matches || !$logPanel.hasClass('collapsed')){
      $preview.empty();
      return;
    }
    var $entries = $logBody.find('.log-entry');
    var $eligible = currentFilter === 'ALL'
      ? $entries
      : $entries.filter(function(){
          return $(this).data('level') === currentFilter;
        });
    var cards = [];
    $eligible.slice(-2).each(function(){
      var $entry = $(this);
      var $card = $(document.createElement('div')).addClass('mobile-log-card');
      var $meta = $(document.createElement('div')).addClass('mobile-log-meta').appendTo($card);
      var $badge = $entry.find('.log-badge');
      if($badge.length){
        // 徽标由常量 class + 级别文本组成（文本经 .text() 生成），整段 clone 不带日志正文
        $meta.append($badge.clone());
      }
      $meta.append(buildLogTextEl('span', 'mobile-log-time', $entry.find('.log-time').text()));
      $card.append(buildLogTextEl('div', 'mobile-log-msg', $entry.find('.log-msg').text()));
      cards.push($card);
    });
    $preview.empty();
    if(!cards.length){
      $preview.append(buildLogTextEl('div', 'mobile-log-empty', '暂无日志'));
    } else {
      for(var i = 0; i < cards.length; i++){
        $preview.append(cards[i]);
      }
    }
  }

  function syncLogViewport(){
    var body = $logBody[0];
    if(!body) return;
    if(window.matchMedia('(max-width: 900px)').matches && $logPanel.hasClass('collapsed')){
      body.scrollTop = 0;
      return;
    }
    if($logPanel.hasClass('expanded')){
      body.scrollTop = body.scrollHeight;
    }
  }

  if(window.matchMedia('(max-width: 900px)').matches){
    $logPanel.removeClass('expanded').addClass('collapsed');
    $('#btnToggleLog i').attr('class','bi bi-chevron-up');
    syncMobileLogTitle();
    syncMobileRecentLogs();
    syncLogViewport();
  }

  function toggleLogPanel(){
    if($logPanel.hasClass('expanded')){
      $logPanel.removeClass('expanded').addClass('collapsed');
      $('#btnToggleLog i').attr('class','bi bi-chevron-up');
    } else {
      $logPanel.removeClass('collapsed').addClass('expanded');
      $('#btnToggleLog i').attr('class','bi bi-chevron-down');
    }
    syncMobileLogTitle();
    syncMobileRecentLogs();
    syncLogViewport();
    if(typeof syncLogPolling === 'function'){
      syncLogPolling(true);
    }
    _saveUiState();   // 记住日志面板的展开状态
  }

  // 点击标题区域或展开/收起按钮都可以切换
  $('#logToolbar .log-title').click(toggleLogPanel);
  $('#btnToggleLog').click(toggleLogPanel);

  // 筛选按钮
  $('.filter-btn').click(function(e){
    e.stopPropagation();
    $('.filter-btn').removeClass('active');
    $(this).addClass('active');
    currentFilter=$(this).data('level');
    filterLogs();
    _saveUiState();   // 记住日志筛选
  });

  function filterLogs(){
    $logBody.find('.log-entry').each(function(){
      if(currentFilter==='ALL') $(this).show();
      else $(this).toggle($(this).data('level')===currentFilter);
    });
    syncMobileRecentLogs();
    syncLogViewport();
  }

  $('#btnClearLog').click(function(e){
    e.stopPropagation();
    $logBody.empty();
    lastLogId=0;
    syncMobileRecentLogs();
    syncLogViewport();
  });

  // ===== 版本更新检查 =====
  var retryTimer = null;
  var retryCount = 0;
  var MAX_RETRY = 3;
  var RETRY_INTERVALS = [10, 20, 30];
  var _hasUpdate = false; // 检测到新版本时置 true

  function checkUpdate(manual) {
    if (manual) {
      clearTimeout(retryTimer);
      retryCount = 0;
      $('#update-retry-hint').text('');
    }
    $('#update-checking').show();
    $('#update-latest, #update-available, #update-error').hide();
    if (manual) $('#btn-check-update').prop('disabled', true).text('检查中...');

    $.ajax({
      url: '/check_update',
      method: 'GET',
      dataType: 'json',
      timeout: 60000,
      success: function(res) {
        retryCount = 0;
        clearTimeout(retryTimer);
        $('#update-retry-hint').text('');
        $('#update-checking').hide();
        var now = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'});
        $('#update-last-check').text('上次检查：' + now + '　每6小时自动检查');
        if (res.status !== 'success') { $('#update-error').show(); return; }

        var latest  = (res.data.version || '').trim();
        var log     = (res.data.version_log || '').trim();
        var current = (res.data.local_version || '').trim();

        if (latest && current && latest !== current) {
          _hasUpdate = true;
          $('#update-new-ver').text(log);
          $('#update-available').show();
          $('#update-card').insertBefore('#status-main-card');
        } else {
          _hasUpdate = false;
          $('#update-current-ver').text('当前版本：' + current);
          $('#update-latest').css('display', 'flex');
          $('#update-card').insertAfter('#status-main-card');
        }

        // 开发者广播通知：有内容时始终插到 status-main-card 前面（顶部显示）
        var infrom = (res.data.infrom || '').trim();
        if (infrom) {
          $('#infrom-content').text(infrom);
          $('#infrom-card').insertBefore('#status-main-card').show();
        } else {
          $('#infrom-card').hide();
        }
      },
      error: function() {
        $('#update-checking').hide();
        $('#update-error').show();
        if (retryCount < MAX_RETRY) {
          var interval = RETRY_INTERVALS[retryCount];
          retryCount++;
          var remaining = interval;
          $('#update-retry-hint').text('将在 ' + remaining + 's 后重试（' + retryCount + '/' + MAX_RETRY + '）');
          var countdown = setInterval(function() {
            remaining--;
            if (remaining <= 0) {
              clearInterval(countdown);
              $('#update-retry-hint').text('');
              checkUpdate(false);
            } else {
              $('#update-retry-hint').text('将在 ' + remaining + 's 后重试（' + retryCount + '/' + MAX_RETRY + '）');
            }
          }, 1000);
          retryTimer = countdown;
        } else {
          $('#update-retry-hint').text('已达最大重试次数，请手动重试');
        }
      },
      complete: function() {
        if (manual) $('#btn-check-update').prop('disabled', false).text('检查更新');
      }
    });
  }

  $('#btn-check-update').on('click', function(e) {
    e.preventDefault();
    checkUpdate(true);
  });

  // ===== Status Panel =====
  function refreshStatus(){
    return $.getJSON('/get_status', function(res){
      if(!res || res.status !== 'success') return;
      var d = res.data;
      var botState = d.bot_state || (d.bot_running ? 'running' : 'stopped');
      if(botState === 'stopping'){
        // 停止中：线程还没退出。既不是"运行中"，也不能说"已停止"——
        // 说成已停止会让人以为可以立刻再启动，而那时启动会被拒绝（防两条线程重叠）。
        $('#topbar-notice').show();
        $('#status-dot').css('background', '#FFB800');
        $('#status-text').text('正在停止...');
        $('#status-sub').text('等待监听线程退出，完成前不会放行再次启动');
        $('#status-uptime').text('');
        return;
      }
      if(d.bot_running){
        $('#topbar-notice').show();
        $('#status-dot').css('background', d.callback_is_die ? '#FA5151' : '#07C160');
        if(botState === 'starting'){
          $('#status-text').text('启动中...');
        } else {
          $('#status-text').text(d.callback_is_die ? '运行异常（回调出错）' : '运行中');
        }
        $('#status-sub').text('微信账号：' + (d.wx_nickname || '获取中...'));
        $('#status-uptime').text('运行时长：' + (d.uptime || '-'));
        $('#sv-received').text(d.msg_received !== undefined ? d.msg_received : '-');
        $('#sv-replied').text(d.msg_replied !== undefined ? d.msg_replied : '-');
        $('#sv-listen').text(d.listen_mode || '-');
        $('#sv-group').text(d.group_switch ? (d.group_count + ' 个') : '未启用');
        $('#sv-schedule').text(d.scheduled_switch ? (d.scheduled_count + ' 个') : '未启用');
        $('#sv-api').text(d.api_sdk || '-');
        $('#dv-nickname').text(d.wx_nickname || '-');
        $('#dv-model').text(d.model || '-');
        $('#dv-start').text(d.start_time || '-');
        $('#dv-version').text(d.version || '-');
        $('#dv-lasttime').text(d.last_msg_time || '暂无');
        $('#dv-lastsender').text(d.last_msg_sender || '暂无');
        // 关键词卡片
        var kwOn = d.chat_keyword_switch || d.group_keyword_switch;
        if(kwOn){
          var kwParts = [];
          if(d.chat_keyword_switch) kwParts.push('私聊');
          if(d.group_keyword_switch) kwParts.push('群聊');
          $('#sv-keyword').text(kwParts.join('/') + ' · ' + (d.keyword_count||0) + '个');
        } else {
          $('#sv-keyword').text('未启用');
        }
        // 记忆卡片
        $('#sv-memory').text(d.memory_switch ? ('上下文' + (d.memory_context_count||'-') + '条') : '未启用');
        // 回复延迟卡片
        $('#sv-delay').text(d.reply_delay_switch ? ((d.reply_delay_min||'-') + '~' + (d.reply_delay_max||'-') + 's') : '未启用');
        // 回复轮数限制卡片
        if (d.chat_max_round_switch) {
          var resetText = d.chat_max_round_reset_days ? ('/' + d.chat_max_round_reset_days + '天') : '';
          $('#sv-max-round').text('上限' + (d.chat_max_round_default||'-') + '轮' + resetText);
        } else {
          $('#sv-max-round').text('未启用');
        }
        // 详情行
        if (d.group_keyword_switch) {
          var kwModes = [d.group_keyword_at_only ? '仅@触发' : '全部触发'];
          if (d.group_keyword_reply_at_msg) kwModes.push('@发言人');
          if (d.keyword_reply_quote) kwModes.push('引用');
          $('#dv-kw-at').text(kwModes.join(' · '));
        } else {
          $('#dv-kw-at').text('-');
        }
        $('#dv-mem-ctx').text(d.memory_switch ? ((d.memory_context_count||'-') + ' 条') : '已关闭');
      } else {
        $('#topbar-notice').hide();
        $('#status-dot').css('background', '#ccc');
        // 只在首次加载（数据还是初始 "-"）时才显示"未运行"占位，否则保留上次数据
        var hasData = $('#sv-received').text() !== '-';
        if (hasData) {
          $('#status-text').text('已停止（上次运行数据）');
          $('#status-sub').text('点击"启动机器人"重新运行');
        } else {
          $('#status-text').text('未运行');
          $('#status-sub').text('点击"启动机器人"开始运行');
        }
        $('#status-uptime').text('');
      }
    });
  }
  var STATUS_POLL_VISIBLE_MS = 5500;
  var STATUS_POLL_HIDDEN_MS = 20000;
  var SIVER_PANEL_POLL_VISIBLE_MS = 5000;
  var SIVER_PANEL_POLL_HIDDEN_MS = 20000;
  var LOG_POLL_VISIBLE_MS = 5000;
  var LOG_POLL_MOBILE_PREVIEW_MS = 6000;
  var LOG_POLL_HIDDEN_MS = 15000;

  var statusPollTimer = null;
  var statusPollInFlight = false;
  var siverPanelPollTimer = null;
  var siverPanelPollInFlight = false;
  var logPollTimer = null;
  var logPollInFlight = false;

  function isForceAdminChangeRequired(){
    return !!window.__FORCE_REMOTE_ADMIN_CHANGE__;
  }

  function shouldPromptAdminChangeForRemoteConnect(){
    return !!window.__REMOTE_CONNECT_BLOCK_REQUIRED__;
  }

  function isStatusTabActive(){
    return getActiveTabId() === 'tab-status';
  }

  function isSiverPanelTabActive(){
    return getActiveTabId() === 'tab-siver-panel';
  }

  function isMobileLogPreviewActive(){
    return isMobileLayout() && $logPanel.hasClass('collapsed');
  }

  function shouldPollLogFeed(){
    return $logPanel.hasClass('expanded') || isMobileLogPreviewActive();
  }

  function getStatusPollDelay(){
    if(isForceAdminChangeRequired()){
      return null;
    }
    if(!isStatusTabActive()){
      return null;
    }
    return isPageVisible() ? STATUS_POLL_VISIBLE_MS : STATUS_POLL_HIDDEN_MS;
  }

  function getSiverPanelPollDelay(){
    if(isForceAdminChangeRequired()){
      return null;
    }
    if(!isSiverPanelTabActive()){
      return null;
    }
    return isPageVisible() ? SIVER_PANEL_POLL_VISIBLE_MS : SIVER_PANEL_POLL_HIDDEN_MS;
  }

  function getLogPollDelay(){
    if(isForceAdminChangeRequired()){
      return null;
    }
    if(!shouldPollLogFeed()){
      return null;
    }
    if(!isPageVisible()){
      return LOG_POLL_HIDDEN_MS;
    }
    if($logPanel.hasClass('expanded')){
      return LOG_POLL_VISIBLE_MS;
    }
    if(isMobileLogPreviewActive()){
      return LOG_POLL_MOBILE_PREVIEW_MS;
    }
    return null;
  }

  function scheduleStatusPolling(delay){
    clearTimeout(statusPollTimer);
    if(delay == null){
      return;
    }
    statusPollTimer = setTimeout(function(){
      triggerStatusPolling(false);
    }, delay);
  }

  function triggerStatusPolling(immediate){
    clearTimeout(statusPollTimer);
    if(statusPollInFlight){
      scheduleStatusPolling(getStatusPollDelay());
      return;
    }
    statusPollInFlight = true;
    refreshStatus().always(function(){
      statusPollInFlight = false;
      scheduleStatusPolling(getStatusPollDelay());
    });
  }

  function syncStatusPolling(immediate){
    if(immediate && isStatusTabActive()){
      triggerStatusPolling(true);
      return;
    }
    scheduleStatusPolling(getStatusPollDelay());
  }

  function scheduleSiverPanelPolling(delay){
    clearTimeout(siverPanelPollTimer);
    if(delay == null){
      return;
    }
    siverPanelPollTimer = setTimeout(function(){
      triggerSiverPanelPolling(false);
    }, delay);
  }

  function triggerSiverPanelPolling(immediate){
    clearTimeout(siverPanelPollTimer);
    var delay = getSiverPanelPollDelay();
    if(delay == null){
      return;
    }
    if(siverPanelPollInFlight){
      scheduleSiverPanelPolling(delay);
      return;
    }
    siverPanelPollInFlight = true;
    refreshSiverPanelStatus().always(function(){
      siverPanelPollInFlight = false;
      scheduleSiverPanelPolling(getSiverPanelPollDelay());
    });
  }

  function syncSiverPanelPolling(immediate){
    if(immediate && isSiverPanelTabActive()){
      triggerSiverPanelPolling(true);
      return;
    }
    scheduleSiverPanelPolling(getSiverPanelPollDelay());
  }

  function scheduleLogPolling(delay){
    clearTimeout(logPollTimer);
    if(delay == null){
      return;
    }
    logPollTimer = setTimeout(function(){
      triggerLogPolling(false);
    }, delay);
  }

  function triggerLogPolling(immediate){
    clearTimeout(logPollTimer);
    var delay = getLogPollDelay();
    if(delay == null){
      return;
    }
    if(logPollInFlight){
      scheduleLogPolling(delay);
      return;
    }
    logPollInFlight = true;
    refreshLogFeed().always(function(){
      logPollInFlight = false;
      scheduleLogPolling(getLogPollDelay());
    });
  }

  function syncLogPolling(immediate){
    var delay = getLogPollDelay();
    if(immediate && delay != null){
      triggerLogPolling(true);
      return;
    }
    scheduleLogPolling(delay);
  }

  document.addEventListener('visibilitychange', function(){
    var immediate = isPageVisible();
    syncStatusPolling(immediate);
    syncSiverPanelPolling(immediate);
    syncLogPolling(immediate);
  });

  syncStatusPolling(true);
  syncSiverPanelPolling(true);
  syncLogPolling(true);
  checkUpdate(false); // 页面加载时自动检查一次
  setInterval(function(){ checkUpdate(false); }, 6 * 60 * 60 * 1000); // 每 6 小时自动检查一次

  // ===== Account Panel =====
  // 进入 tab 时加载当前用户名
  $(document).on('click', '[data-tab="tab-account"]', function(){
    $.getJSON('/get_admin_config', function(res){
      if(res.status === 'success'){
        $('#acc-username').val(res.username);
        $('#force-acc-username').val(res.username);
      }
    });
  });
  function showMsg(id, msg, ok){
    var $el = $('#'+id);
    $el.text(msg)
       .css({'background': ok ? '#F0FBF5' : '#FFF0F0',
             'border': '1px solid ' + (ok ? '#B7EBD0' : '#FECACA'),
             'color': ok ? '#06AD56' : '#DC2626'})
       .show();
    setTimeout(function(){ $el.hide(); }, 3500);
  }
  function showForceAdminChangeMsg(msg, ok){
    var $el = $('#force-admin-change-msg');
    $el.text(msg)
       .css({
         'background': ok ? '#F0FBF5' : '#FFF0F0',
         'border': '1px solid ' + (ok ? '#B7EBD0' : '#FECACA'),
        'color': ok ? '#06AD56' : '#DC2626'
      })
       .show();
  }
  function setPendingRemoteConnectAfterAdminChange(value){
    window.__PENDING_REMOTE_CONNECT_AFTER_ADMIN_CHANGE__ = !!value;
  }
  function syncAccountUsername(username){
    if(typeof username !== 'string') return;
    $('#acc-username').val(username);
    $('#force-acc-username').val(username);
    $('.topbar-username').text(username);
  }
  function unlockForceAdminChange(){
    window.__FORCE_REMOTE_ADMIN_CHANGE__ = false;
    window.__REMOTE_CONNECT_BLOCK_REQUIRED__ = false;
    setPendingRemoteConnectAfterAdminChange(false);
    $('#force-admin-change-overlay').hide();
    $('#force-admin-change-msg').hide();
    syncStatusPolling(true);
    syncSiverPanelPolling(true);
    syncLogPolling(true);
  }
  function requestRemoteConnect(options){
    options = options || {};
    var pollAfterSuccess = options.pollAfterSuccess !== false;
    var showConnectingState = options.showConnectingState !== false;
    if(showConnectingState){
      renderSiverPanelStatus({
        state:'connecting',
        enabled: $('#siver_panel_enabled').is(':checked'),
        slug: normalizeSiverPanelSlug($('#siver_panel_slug').val()),
        last_message:'正在发起远程连接，请稍候...'
      });
    }
    $.ajax({
      url:'/api/siver-panel/connect',
      type:'POST',
      contentType:'application/json',
      data: JSON.stringify({}),
      success:function(res){
        if(res.status !== 'success'){
          if((res.error_code || '') === 'default_admin_credentials_block_remote_connect' || (res.data && res.data.last_error_code === 'default_admin_credentials_block_remote_connect')){
            window.__REMOTE_CONNECT_BLOCK_REQUIRED__ = true;
            setPendingRemoteConnectAfterAdminChange(true);
            openForceAdminChangeOverlay();
            return;
          }
          setPendingRemoteConnectAfterAdminChange(false);
          svModal.error(res.message || '远程连接发起失败');
        } else {
          setPendingRemoteConnectAfterAdminChange(false);
          if(pollAfterSuccess){
            pollSiverPanelStatusForModal();
          }
        }
        setTimeout(refreshSiverPanelStatus, 250);
      },
      error:function(xhr){
        setPendingRemoteConnectAfterAdminChange(false);
        svModal.error('远程连接请求失败：' + xhr.status);
        setTimeout(refreshSiverPanelStatus, 250);
      }
    });
  }
  function saveAdminCredentials(options){
    options = options || {};
    var username = String(options.username || '').trim();
    var password = options.password || '';
    var onSuccess = options.onSuccess || function(){};
    var onError = options.onError || function(msg){ showMsg('acc-msg', msg, false); };
    $.ajax({
      url:'/save_admin_config',
      type:'POST',
      contentType:'application/json',
      data: JSON.stringify({username: username, password: password}),
      success: function(res){
        if(res.status === 'success'){
          syncAccountUsername(res.username || username);
          onSuccess(res);
          return;
        }
        onError(res.message || '保存失败');
      },
      error: function(xhr){
        onError('请求失败: ' + xhr.responseText);
      }
    });
  }
  $('#btn-save-account').click(function(){
    var u = $('#acc-username').val().trim();
    var p = $('#acc-password').val();
    var p2 = $('#acc-password2').val();
    if(!u || !p){ showMsg('acc-msg','用户名和密码不能为空',false); return; }
    if(p !== p2){ showMsg('acc-msg','两次输入的密码不一致',false); return; }
    $.ajax({ url:'/save_admin_config', type:'POST', contentType:'application/json',
      data: JSON.stringify({username:u, password:p}),
      success: function(res){
        showMsg('acc-msg', res.message, res.status==='success');
        if(res.status==='success'){
          syncAccountUsername(res.username || u);
          $('#acc-password').val('');
          $('#acc-password2').val('');
          window.__REMOTE_CONNECT_BLOCK_REQUIRED__ = false;
          if(!res.force_admin_change_required){
            unlockForceAdminChange();
          }
        }
      },
      error: function(xhr){ showMsg('acc-msg','请求失败: '+xhr.responseText, false); }
    });
  });
  function openForceAdminChangeOverlay(){
    var requireRemoteLoginChange = isForceAdminChangeRequired();
    var requireRemoteConnectChange = shouldPromptAdminChangeForRemoteConnect();
    if(!(requireRemoteLoginChange || requireRemoteConnectChange)){
      return;
    }
    $('#sv-modal-overlay').hide();
    activateTab('tab-account');
    $('#force-acc-password').val('');
    $('#force-acc-password2').val('');
    $('#force-admin-change-msg').hide();
    if(requireRemoteLoginChange){
      setPendingRemoteConnectAfterAdminChange(false);
      $('#force-admin-change-title').text('远程访问禁止使用默认账号密码');
      $('#force-admin-change-body').html('当前是通过远程访问链接登录，且仍在使用默认账号 <code>admin</code> / 密码 <code>123456</code>。<br>为了安全，必须先修改后台账号密码，修改完成后才可以继续使用面板。');
    } else {
      setPendingRemoteConnectAfterAdminChange(true);
      $('#force-admin-change-title').text('连接远程服务前必须先修改默认账号密码');
      $('#force-admin-change-body').html('当前后台仍在使用默认账号 <code>admin</code> / 密码 <code>123456</code>。<br>为了安全，必须先修改后台账号密码，修改完成后才可以继续连接远程访问服务。');
    }
    $.getJSON('/get_admin_config', function(res){
      if(res.status === 'success'){
        syncAccountUsername(res.username || '');
      }
      $('#force-admin-change-overlay').css('display', 'flex');
      setTimeout(function(){ $('#force-acc-username').focus(); }, 100);
    }).fail(function(){
      $('#force-admin-change-overlay').css('display', 'flex');
      setTimeout(function(){ $('#force-acc-username').focus(); }, 100);
    });
  }
  $('#force-admin-change-submit').on('click', function(){
    var u = $('#force-acc-username').val().trim();
    var p = $('#force-acc-password').val();
    var p2 = $('#force-acc-password2').val();
    if(!u || !p){
      showForceAdminChangeMsg('用户名和密码不能为空', false);
      return;
    }
    if(p !== p2){
      showForceAdminChangeMsg('两次输入的密码不一致', false);
      return;
    }
    var $btn = $(this);
    $btn.prop('disabled', true).text('保存中...');
    showForceAdminChangeMsg('正在保存新的账号密码...', true);
    saveAdminCredentials({
      username: u,
      password: p,
      onSuccess: function(res){
        $btn.prop('disabled', false).text('保存并继续使用');
        $('#acc-password').val('');
        $('#acc-password2').val('');
        $('#force-acc-password').val('');
        $('#force-acc-password2').val('');
        showForceAdminChangeMsg(res.message || '账号密码已保存', true);
        if(!res.force_admin_change_required){
          var shouldReconnectRemote = !!window.__PENDING_REMOTE_CONNECT_AFTER_ADMIN_CHANGE__;
          unlockForceAdminChange();
          if(shouldReconnectRemote){
            requestRemoteConnect({showConnectingState:true});
          }
        }
      },
      onError: function(msg){
        $btn.prop('disabled', false).text('保存并继续使用');
        showForceAdminChangeMsg(msg, false);
      }
    });
  });
  if(isForceAdminChangeRequired()){
    openForceAdminChangeOverlay();
  } else if(shouldPromptAdminChangeForRemoteConnect()){
    openForceAdminChangeOverlay();
  }

  // ===== Email Panel =====
  $(document).on('click', '[data-tab="tab-email"]', function(){
    $.getJSON('/get_email_config', function(res){
      if(res.status === 'success'){
        $('#email-host').val(res.host);
        $('#email-port').val(res.port);
        $('#email-user').val(res.user);
        $('#email-pass').val(res.pass);
      }
    });
  });
  $('#btn-save-email').click(function(){
    var d = { host:$('#email-host').val().trim(), port:$('#email-port').val().trim(),
              user:$('#email-user').val().trim(), pass:$('#email-pass').val() };
    if(!d.host||!d.port||!d.user||!d.pass){ showMsg('email-msg','所有字段均不能为空',false); return; }
    $.ajax({ url:'/save_email_config', type:'POST', contentType:'application/json',
      data: JSON.stringify(d),
      success: function(res){ showMsg('email-msg', res.message, res.status==='success'); },
      error: function(xhr){ showMsg('email-msg','请求失败: '+xhr.responseText, false); }
    });
  });



  // ===== Webhook Panel =====
  function collectWebhookConfig(){
    var headers = {};
    var headerText = $('#webhook-headers').val().trim();
    if(headerText){
      try { headers = JSON.parse(headerText); }
      catch(e){ showMsg('webhook-msg','Headers 不是合法 JSON: '+e.message,false); return null; }
    }
    return {
      enabled: $('#webhook-enabled').is(':checked'),
      url: $('#webhook-url').val().trim(),
      method: $('#webhook-method').val(),
      content_type: $('#webhook-content-type').val().trim() || 'application/json',
      headers: headers,
      body: $('#webhook-body').val(),
      timeout: parseInt($('#webhook-timeout').val() || '5', 10)
    };
  }
  function loadWebhookConfig(){
    $.getJSON('/get_webhook_config', function(res){
      if(res.status === 'success'){
        $('#webhook-enabled').prop('checked', !!res.enabled);
        $('#webhook-url').val(res.url || '');
        $('#webhook-method').val(res.method || 'POST');
        $('#webhook-content-type').val(res.content_type || 'application/json');
        $('#webhook-timeout').val(res.timeout || 5);
        $('#webhook-headers').val(JSON.stringify(res.headers || {}, null, 2));
        $('#webhook-body').val(res.body || '{"title":"$title","content":"$content"}');
      } else {
        showMsg('webhook-msg', res.message || '加载 Webhook 配置失败', false);
      }
    });
  }
  $(document).on('click', '[data-tab="tab-webhook"]', loadWebhookConfig);
  $('#btn-save-webhook').click(function(){
    var d = collectWebhookConfig(); if(!d) return;
    if(d.enabled && !d.url){ showMsg('webhook-msg','启用 Webhook 时 URL 不能为空',false); return; }
    $.ajax({ url:'/save_webhook_config', type:'POST', contentType:'application/json',
      data: JSON.stringify(d),
      success: function(res){ showMsg('webhook-msg', res.message, res.status==='success'); },
      error: function(xhr){ showMsg('webhook-msg','请求失败: '+xhr.responseText, false); }
    });
  });
  $('#btn-test-webhook').click(function(){
    var d = collectWebhookConfig(); if(!d) return;
    d.enabled = true;
    if(!d.url){ showMsg('webhook-msg','测试 Webhook 时 URL 不能为空',false); return; }
    $.ajax({ url:'/test_webhook', type:'POST', contentType:'application/json',
      data: JSON.stringify(d),
      success: function(res){ showMsg('webhook-msg', res.message, res.status==='success'); },
      error: function(xhr){ showMsg('webhook-msg','请求失败: '+xhr.responseText, false); }
    });
  });

  // ===== Memory Panel =====
  var _memWxId = null, _memChatName = null;

  // 渲染一条消息气泡
  function _renderMemoryMsg(m){
    var attr    = m.attr || '';
    var content = $('<span>').text(m.content).html();
    var t       = m.time || '';
    if(attr === 'self'){
      return '<div class="msg-bubble-wrap right">' +
        '<div class="msg-bubble right">'+content+'</div>' +
        '<div class="msg-time">'+t+'</div></div>';
    } else if(attr === 'system' || attr === 'time'){
      return '<div class="msg-bubble-wrap center">' +
        '<div class="msg-bubble center">'+content+'</div></div>';
    } else {
      return '<div class="msg-bubble-wrap left">' +
        '<div class="msg-sender">'+($('<span>').text(m.sender||'').html())+'</div>' +
        '<div class="msg-bubble left">'+content+'</div>' +
        '<div class="msg-time">'+t+'</div></div>';
    }
  }

  // 加载并渲染消息列表
  function loadMemoryMessages(wxid, chatKey, chatName){
    var $c = $('#memory-msg-container');
    $('#memory-msg-title').text(chatName || chatKey);
    $('#memory-msg-count').text('加载中...');
    $c.html('<div style="text-align:center;color:var(--muted);font-size:13px;padding:20px;">加载中...</div>');
    $.getJSON('/memory/data/'+encodeURIComponent(wxid)+'/'+encodeURIComponent(chatKey))
      .done(function(res){
        $c.empty();
        if(res.status !== 'success' || !res.messages.length){
          $('#memory-msg-count').text('0 条');
          $c.html('<div style="text-align:center;color:var(--muted);font-size:13px;padding:20px;">暂无消息记录</div>');
          return;
        }
        $('#memory-msg-count').text('共 ' + res.messages.length + ' 条');
        var html = '';
        res.messages.forEach(function(m){ html += _renderMemoryMsg(m); });
        $c.html(html);
        var $area = $('#memory-msg-area')[0];
        if($area) $area.scrollTop = $area.scrollHeight;
      })
      .fail(function(xhr){
        $('#memory-msg-count').text('');
        $c.html('<div style="text-align:center;color:var(--danger);font-size:13px;padding:20px;">加载失败: '+xhr.status+'</div>');
      });
  }

  // 加载窗口列表；若 autoSelect 有值则自动选中对应窗口并加载消息
  function loadMemoryChatList(wxid, autoSelect){
    $.getJSON('/memory/chats/'+encodeURIComponent(wxid))
      .done(function(res){
        var $list = $('#memory-chat-list').empty();
        if(res.status !== 'success' || !res.chats.length){
          $list.html('<div style="padding:12px;font-size:12.5px;color:var(--muted);">暂无对话窗口</div>');
          return;
        }
        res.chats.forEach(function(chatItem){
          var chatName = (typeof chatItem === 'string') ? chatItem : (chatItem.name || chatItem.storage_name || '');
          var chatKey  = (typeof chatItem === 'string') ? chatItem : (chatItem.storage_name || chatItem.name || '');
          var $item = $('<div class="memory-list-item">' +
            '<span class="item-name" title="'+$('<span>').text(chatName).html()+'">'+$('<span>').text(chatName).html()+'</span>' +
            '<button type="button" class="btn-del-mem" title="删除"><i class="bi bi-trash"></i></button>' +
            '</div>');
          // 如果是自动恢复选中的那一项，立即标记 selected
          if(chatKey === autoSelect) $item.addClass('selected');
          $item.on('click', function(e){
            if($(e.target).closest('.btn-del-mem').length) return;
            $('.memory-list-item','#memory-chat-list').removeClass('selected');
            $item.addClass('selected');
            _memChatName = chatKey;
            $('#memory-msg-area').show().css('display','flex');
            loadMemoryMessages(wxid, chatKey, chatName);
          });
          $item.find('.btn-del-mem').on('click', function(){
            svModal.confirm('确定删除窗口「'+chatName+'」的记忆？', function(){
              $.ajax({ url:'/memory/delete_chat/'+encodeURIComponent(wxid)+'/'+encodeURIComponent(chatKey), type:'DELETE' })
                .done(function(r){
                  if(r.status==='success'){
                    if(_memChatName===chatKey){ _memChatName=null; $('#memory-msg-area').hide(); $('#memory-msg-container').empty(); }
                    loadMemoryChatList(wxid);
                  } else { svModal.error(r.message||'删除失败'); }
                });
            }, '删除确认');
          });
          $list.append($item);
        });
        // 自动恢复：若之前有选中的窗口，立即加载其消息
        if(autoSelect){
          var selectedChat = null;
          res.chats.some(function(chatItem){
            var chatName = (typeof chatItem === 'string') ? chatItem : (chatItem.name || chatItem.storage_name || '');
            var chatKey  = (typeof chatItem === 'string') ? chatItem : (chatItem.storage_name || chatItem.name || '');
            if(chatKey === autoSelect){
              selectedChat = {key: chatKey, name: chatName};
              return true;
            }
            return false;
          });
          if(selectedChat){
            $('#memory-msg-area').show().css('display','flex');
            loadMemoryMessages(wxid, selectedChat.key, selectedChat.name);
          }
        }
      })
      .fail(function(xhr){
        $('#memory-chat-list').html('<div style="padding:12px;font-size:12.5px;color:var(--danger);">加载失败: '+xhr.status+'</div>');
      });
  }

  // 加载微信号列表；若 autoWx 有值则自动选中并恢复子级选中状态
  function loadMemoryWxList(autoWx, autoChat){
    $.getJSON('/memory/list')
      .done(function(res){
        var $list = $('#memory-wx-list').empty();
        if(res.status !== 'success' || !res.wx_ids.length){
          $list.html('<div style="padding:12px;font-size:12.5px;color:var(--muted);">暂无记忆数据</div>');
          return;
        }
        res.wx_ids.forEach(function(wxid){
          var $item = $('<div class="memory-list-item">' +
            '<span class="item-name" title="'+$('<span>').text(wxid).html()+'">'+$('<span>').text(wxid).html()+'</span>' +
            '<button type="button" class="btn-del-mem" title="删除"><i class="bi bi-trash"></i></button>' +
            '</div>');
          if(wxid === autoWx) $item.addClass('selected');
          $item.on('click', function(e){
            if($(e.target).closest('.btn-del-mem').length) return;
            $('.memory-list-item','#memory-wx-list').removeClass('selected');
            $item.addClass('selected');
            _memWxId = wxid; _memChatName = null;
            $('#memory-chat-panel').show();
            $('#memory-msg-area').hide();
            $('#memory-msg-container').empty();
            loadMemoryChatList(wxid);
          });
          $item.find('.btn-del-mem').on('click', function(){
            svModal.confirm('确定删除微信号「'+wxid+'」的所有记忆？', function(){
              $.ajax({ url:'/memory/delete_wx/'+encodeURIComponent(wxid), type:'DELETE' })
                .done(function(r){
                  if(r.status==='success'){
                    if(_memWxId===wxid){ _memWxId=null; _memChatName=null; $('#memory-chat-panel').hide(); $('#memory-msg-area').hide(); $('#memory-msg-container').empty(); }
                    loadMemoryWxList();
                  } else { svModal.error(r.message||'删除失败'); }
                });
            }, '删除确认');
          });
          $list.append($item);
        });
        // 自动恢复选中状态，并级联加载子列表
        if(autoWx && res.wx_ids.indexOf(autoWx) !== -1){
          $('#memory-chat-panel').show();
          loadMemoryChatList(autoWx, autoChat||undefined);
        }
      })
      .fail(function(xhr){
        $('#memory-wx-list').html('<div style="padding:12px;font-size:12.5px;color:var(--danger);">加载失败: '+xhr.status+'</div>');
      });
  }

  // 进入记忆标签时加载列表
  $(document).on('click', '[data-tab="tab-memory"]', function(){
    loadMemoryWxList();
  });
  // 刷新按钮：保留当前选中的微信号和窗口，刷新后自动恢复并更新消息
  $(document).on('click', '#btn-refresh-memory', function(){
    loadMemoryWxList(_memWxId||undefined, _memChatName||undefined);
  });

  // ===== Log Polling =====
  function parseLogId(value){
    var logId = parseInt(value, 10);
    return isNaN(logId) ? 0 : logId;
  }
  // 日志内容装的是微信消息原文（发送人/内容），一律按纯文本渲染：
  // 拼成 HTML 字符串再 insert 等于「谁给机器人发一条含标签的消息，谁就能在管理员
  // 面板里执行任意脚本」——面板没有任何 CSP，jQuery 的 .append(html) 还会执行
  // <script>。这里只创建 DOM 节点，所有文本走 .text()（等价 textContent）。
  // 需要富文本的只有 svModal 弹窗那条独立路径（见文件顶部注释），日志不得复用它。
  function buildLogTextEl(tag, className, text){
    var $el = $(document.createElement(tag));
    if(className) $el.addClass(className);
    $el.text(text == null ? '' : String(text));
    return $el;
  }
  function buildLogEntry(log){
    var lvl = (log.level||'INFO').toUpperCase();
    var levelMap={INFO:'log-info',SUCCESS:'log-success',WARNING:'log-warning',ERROR:'log-error',DEBUG:'log-debug'};
    var cls = levelMap[lvl]||'log-info';
    var $entry = $(document.createElement('div'))
      .addClass('log-entry')
      .attr('data-level', lvl)
      .attr('data-log-id', parseLogId(log.id));
    $entry.append(buildLogTextEl('span', 'log-time', log.time));
    $entry.append(buildLogTextEl('span', 'log-badge '+cls, lvl));
    $entry.append(buildLogTextEl('span', 'log-msg', log.message));
    return $entry;
  }
  var lastLogId = (function(){
    var last = $logBody.find('.log-entry').last();
    return last.length ? parseLogId(last.attr('data-log-id')) : 0;
  })();
  function refreshLogFeed(){
    var query = {};
    if(lastLogId > 0){
      query.after_id = lastLogId;
    }
    return $.getJSON('/get_logs', query, function(data){
      if(data.reset){
        $logBody.empty();
        lastLogId = 0;
      }
      if(!data.logs || !data.logs.length) return;
      for(var i = 0; i < data.logs.length; i++){
        var log = data.logs[i];
        $logBody.append(buildLogEntry(log));
        lastLogId = Math.max(lastLogId, parseLogId(log.id));
      }
      filterLogs();
      if($logPanel.hasClass('expanded')){
        $logBody.scrollTop($logBody[0].scrollHeight);
      }
    });
  }

  // ===== checkActivate =====
  var _activateStatus = null; // null=未知, true=已激活, false=未激活

  window.checkActivate = function(manual) {
    if (manual) $('#btn-check-activate').prop('disabled', true).text('检测中...');
    $('#activate-card').show();
    $('#activate-checking').show();
    $('#activate-ok, #activate-fail, #activate-error').hide();
    $.ajax({
      url: '/check_activate',
      method: 'GET',
      dataType: 'json',
      timeout: 60000,
      success: function(res) {
        $('#activate-checking').hide();
        if (res.status !== 'success') { $('#activate-error').show(); return; }
        _activateStatus = res.data.activated;
        if (_activateStatus) {
          $('#activate-ok').css('display', 'flex');
          $('#activate-card').insertAfter('#status-main-card');
        } else {
          $('#activate-fail').show();
          $('#activate-card').insertBefore('#status-main-card');
        }
      },
      error: function() {
        $('#activate-checking').hide();
        $('#activate-error').show();
        _activateStatus = null;
      },
      complete: function() {
        if (manual) $('#btn-check-activate').prop('disabled', false).text('重新检测');
      }
    });
  }

  $('#btn-check-activate').on('click', function() { checkActivate(true); });
  checkActivate(false);

  // ===== 刷新后恢复现场：当前 tab / 滚动位置 / 日志面板状态 =====
  // 只写在 sessionStorage 里，关掉标签页即失效，不污染长期状态。
  // 「放弃修改并重新加载」和浏览器 F5 都会走这套恢复。
  // _uiStateReady：初始化期间 activateTab() 会被调用（如切换到账号密码页），
  // 那时若记录就会把上次保存的状态覆盖掉，所以恢复完成前一律不记录。
  var _uiStateReady = false;

  function _saveUiState(){
    if(!_uiStateReady) return;
    try{
      sessionStorage.setItem('dsh_ui_state', JSON.stringify({
        tab:       getActiveTabId(),
        scrollY:   window.scrollY || document.documentElement.scrollTop || 0,
        logExpand: $logPanel.hasClass('expanded'),
        logFilter: currentFilter
      }));
    }catch(e){ /* 隐私模式下 sessionStorage 可能不可用，忽略即可 */ }
  }

  function _restoreUiState(){
    var st = null;
    try{ st = JSON.parse(sessionStorage.getItem('dsh_ui_state') || 'null'); }catch(e){ st = null; }
    _uiStateReady = true;   // 从这里开始才允许记录
    if(!st || typeof st !== 'object') return;

    // 1) 回到原来那个 tab（导航项和面板都存在才恢复）
    if(st.tab && $('.sidebar .nav-link[data-tab="' + st.tab + '"]').length && $('#' + st.tab).length){
      activateTab(st.tab);
    }
    // 2) 日志面板：桌面端恢复展开状态；移动端保持脚本强制的收起
    if(!isMobileLayout() && st.logExpand === false){
      $logPanel.removeClass('expanded').addClass('collapsed');
      $('#btnToggleLog i').attr('class','bi bi-chevron-up');
    }
    // 3) 日志筛选
    if(st.logFilter){
      currentFilter = st.logFilter;
      $('.filter-btn').removeClass('active');
      $('.filter-btn[data-level="' + st.logFilter + '"]').addClass('active');
      filterLogs();
    }
    syncMobileLogTitle();
    syncMobileRecentLogs();
    syncLogViewport();
    // 4) 滚动位置：等本轮渲染结束后再滚，否则会被后续布局拉回顶部
    if(st.scrollY){
      var _y = st.scrollY;
      setTimeout(function(){ window.scrollTo(0, _y); }, 0);
    }
  }

  // 离开页面前再记录一次（主要为了拿到最新的滚动位置）
  $(window).on('beforeunload', _saveUiState);

  _restoreUiState();

});

// ============================================================
// 行内事件处理器调用的全局函数（供 HTML 的 onchange 属性调用）
// 注意：这些函数必须保持全局作用域，不能包进闭包或 IIFE
// ============================================================
// 自定义转发：全部来源开关
function toggleFwdAllSources(cb) {
  $(cb).closest('.mb-3').find('.fwd-manual-sources').toggle(!cb.checked);
}
// 图片识别接口下拉框显示/隐藏（全局函数，供 onchange 调用）
function toggleChatImgApi(checked) {
  document.getElementById('chat_img_api_row').style.display = checked ? 'flex' : 'none';
}
function toggleGroupImgApi(checked) {
  document.getElementById('group_img_api_row').style.display = checked ? 'flex' : 'none';
}
// 拆分多条回复设置区块显示/隐藏
function toggleChatSplitReply(checked) {
  document.getElementById('chat_split_settings').style.display = checked ? '' : 'none';
}
function toggleGroupSplitReply(checked) {
  document.getElementById('group_split_settings').style.display = checked ? '' : 'none';
}
// 多条消息合并回复设置区块显示/隐藏
function toggleMergeReply(checked) {
  document.getElementById('merge_reply_settings').style.display = checked ? '' : 'none';
}
