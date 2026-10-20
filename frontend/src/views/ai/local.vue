<template>
  <div class="local-page">
    <!-- 系统状态 -->
    <el-card class="box-card sys-card" shadow="never">
      <div class="sys-row">
        <span class="card-title">本地模型</span>
        <template v-if="sys">
          <span class="sys-item">
            <el-icon><Monitor /></el-icon>
            <template v-if="sys.gpu">
              {{ sys.gpu.name }} · 显存 {{ sys.gpu.usedGB.toFixed(1) }}/{{ sys.gpu.totalGB.toFixed(1) }} GB
              <el-progress class="sys-bar" :percentage="pct(sys.gpu.usedGB, sys.gpu.totalGB)" :show-text="false" :stroke-width="6" />
            </template>
            <template v-else>未检测到 NVIDIA GPU</template>
          </span>
          <span class="sys-item">内存空闲 {{ sys.ram.freeGB.toFixed(1) }}/{{ sys.ram.totalGB.toFixed(0) }} GB</span>
          <span class="sys-item">模型盘剩余 {{ sys.diskFreeGB.toFixed(0) }} GB</span>
          <el-tag :type="sys.deps.torch.cuda ? 'success' : 'danger'" size="small">
            {{ sys.deps.torch.installed ? `torch ${sys.deps.versions.torch}${sys.deps.torch.cuda ? ' · CUDA ' + sys.deps.torch.cudaVersion : ' · 无 CUDA'}` : '未安装 torch' }}
          </el-tag>
          <el-tag :type="sys.deps.qloraReady ? 'success' : 'warning'" size="small">
            {{ sys.deps.qloraReady ? 'QLoRA 可用' : 'QLoRA 不可用' }}
          </el-tag>
        </template>
        <el-button class="sys-refresh" :icon="Refresh" circle size="small" @click="refreshAll" />
      </div>
      <el-alert
        v-if="sys && !sys.deps.ready"
        class="sys-alert"
        type="warning"
        show-icon
        :closable="false"
        title="未安装本地模型依赖，推理与训练不可用"
        description="在 python-service 目录先安装 CUDA 版 torch，再执行 pip install -r requirements-local.txt（详见该文件注释），然后重启 AI 服务。"
      />
      <el-alert v-if="loadError" class="sys-alert" type="error" show-icon :closable="false" :title="loadError" />
    </el-card>

    <el-card class="box-card" shadow="never">
      <el-tabs v-model="tab">
        <!-- ======================= 基础模型 ======================= -->
        <el-tab-pane label="基础模型" name="models">
          <div class="toolbar">
            <el-button type="primary" :icon="FolderAdd" @click="registerDlg.visible = true">登记本地模型</el-button>
            <el-button :icon="Download" @click="downloadDlg.visible = true">下载模型</el-button>
            <span class="toolbar-hint">登记只记录路径、不复制文件；仅支持 Hugging Face 格式（config.json + safetensors），GGUF 不能用于训练</span>
          </div>
          <el-empty v-if="!models.length" description="还没有基础模型，请登记本机已有的模型目录或下载一个小模型" />
          <el-table v-else :data="models" stripe>
            <el-table-column prop="name" label="名称" min-width="170" show-overflow-tooltip />
            <el-table-column label="类型" min-width="150">
              <template #default="{ row }">{{ row.modelType }} · {{ row.architecture }}</template>
            </el-table-column>
            <el-table-column label="参数 / 大小" width="140">
              <template #default="{ row }">{{ (row.numParams / 1e9).toFixed(2) }}B · {{ gb(row.sizeBytes) }}</template>
            </el-table-column>
            <el-table-column label="路径" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-if="row.managed" size="small" effect="plain">models/</el-tag> {{ row.path }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag v-if="!row.exists" type="danger" size="small">目录不存在</el-tag>
                <el-tag v-else :type="LOAD_STATUS[row.loadStatus].type" size="small">{{ LOAD_STATUS[row.loadStatus].label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="210" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :disabled="!row.exists" @click="goInfer(row.id)">推理测试</el-button>
                <el-button link type="primary" :disabled="!row.exists" @click="goTrain(row.id)">风格微调</el-button>
                <el-button link type="danger" @click="onDeleteModel(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ======================= 风格微调 ======================= -->
        <el-tab-pane label="风格微调" name="train">
          <el-form :model="train" label-width="110px" class="train-form">
            <el-form-item label="基础模型" required>
              <el-select v-model="train.baseModelId" placeholder="选择基础模型" style="width: 360px">
                <el-option
                  v-for="m in models.filter((x) => x.exists)"
                  :key="m.id"
                  :label="`${m.name}（${(m.numParams / 1e9).toFixed(1)}B）`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="适配器名称" required>
              <el-input v-model="train.adapterName" placeholder="如：我的武侠文风 v1" maxlength="100" style="width: 360px" />
            </el-form-item>
            <el-form-item label="方法">
              <el-radio-group v-model="train.method">
                <el-radio-button value="qlora" :disabled="!sys?.deps.qloraReady">QLoRA（4-bit，省显存）</el-radio-button>
                <el-radio-button value="lora">LoRA（16-bit）</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="写作样本" required>
              <div class="samples">
                <el-input
                  v-model="train.sampleText"
                  type="textarea"
                  :autosize="{ minRows: 6, maxRows: 14 }"
                  placeholder="粘贴你自己的文字（建议 1 万字以上，风格越统一越好）"
                />
                <div class="samples-files">
                  <el-select
                    v-model="train.sampleFileIds"
                    multiple
                    filterable
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="或从「文件管理」选择文本文件（txt / md / docx / pdf）"
                    style="width: 100%"
                  >
                    <el-option v-for="f in textFiles" :key="f.id" :label="`${f.fileName}（${kb(f.fileSize)}）`" :value="f.id" />
                  </el-select>
                </div>
                <div class="hint">粘贴 {{ train.sampleText.length }} 字<template v-if="train.sampleFileIds.length"> + {{ train.sampleFileIds.length }} 个文件</template>；至少 500 字</div>
              </div>
            </el-form-item>
            <el-collapse class="adv">
              <el-collapse-item title="训练参数（默认值适合 8GB 显存）" name="adv">
                <div class="adv-grid">
                  <el-form-item label="训练轮数"><el-input-number v-model="train.epochs" :min="1" :max="50" /></el-form-item>
                  <el-form-item label="学习率"><el-input-number v-model="train.learningRate" :min="0.00001" :max="0.01" :step="0.0001" :precision="5" /></el-form-item>
                  <el-form-item label="序列长度"><el-input-number v-model="train.maxSeqLen" :min="128" :max="4096" :step="128" /></el-form-item>
                  <el-form-item label="Batch"><el-input-number v-model="train.batchSize" :min="1" :max="16" /></el-form-item>
                  <el-form-item label="梯度累积"><el-input-number v-model="train.gradAccum" :min="1" :max="64" /></el-form-item>
                  <el-form-item label="最大步数"><el-input-number v-model="train.maxSteps" :min="0" :max="100000" /><span class="hint">0 = 按轮数</span></el-form-item>
                  <el-form-item label="LoRA r"><el-input-number v-model="train.loraR" :min="1" :max="128" /></el-form-item>
                  <el-form-item label="LoRA alpha"><el-input-number v-model="train.loraAlpha" :min="1" :max="256" /></el-form-item>
                  <el-form-item label="Dropout"><el-input-number v-model="train.loraDropout" :min="0" :max="0.5" :step="0.05" :precision="2" /></el-form-item>
                </div>
              </el-collapse-item>
            </el-collapse>
            <el-form-item label="资源评估">
              <el-alert
                v-if="trainEstimate"
                :type="EST_TYPE[trainEstimate.level]"
                :closable="false"
                show-icon
                :title="`预计显存 ${trainEstimate.vramNeedGB} GB / 可用 ${trainEstimate.vramFreeGB} GB；加载内存 ${trainEstimate.ramNeedGB} GB / 空闲 ${trainEstimate.ramFreeGB} GB`"
                :description="trainEstimate.messages.join('；')"
              />
              <span v-else class="hint">选择基础模型后自动评估</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="VideoPlay" :loading="starting" :disabled="!!activeJob" @click="onStartTraining()">开始训练</el-button>
              <span v-if="activeJob" class="hint">已有任务进行中，完成后才能开始新任务</span>
            </el-form-item>
          </el-form>

          <div class="section-title">任务记录</div>
          <el-table :data="jobList" stripe size="small" empty-text="暂无任务">
            <el-table-column label="任务" min-width="210">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.kind === 'train' ? '训练' : '下载' }}</el-tag>
                {{ row.kind === 'train' ? row.config.adapterName : row.config.repoId }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }"><el-tag :type="JOB_STATUS[row.status].type" size="small">{{ JOB_STATUS[row.status].label }}</el-tag></template>
            </el-table-column>
            <el-table-column label="进度" min-width="200">
              <template #default="{ row }">
                <template v-if="row.progress?.maxSteps">
                  <el-progress :percentage="pct(row.progress.step, row.progress.maxSteps)" :status="row.status === 'failed' ? 'exception' : row.status === 'succeeded' ? 'success' : ''" />
                  <span class="hint">step {{ row.progress.step }}/{{ row.progress.maxSteps }}<template v-if="row.progress.loss != null"> · loss {{ row.progress.loss }}</template><template v-if="row.status === 'running' && row.progress.eta != null"> · 剩余约 {{ duration(row.progress.eta) }}</template></span>
                </template>
                <span v-else-if="row.status === 'running'" class="hint">{{ row.kind === 'train' ? '加载模型 / 准备数据中…' : '下载中…（见日志）' }}</span>
                <span v-if="row.error" class="job-error" :title="row.error">{{ row.error }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="createdAt" label="创建时间" width="160" />
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openLog(row)">日志</el-button>
                <el-button v-if="['queued', 'running'].includes(row.status)" link type="danger" @click="onCancelJob(row)">取消</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ======================= LoRA 适配器 ======================= -->
        <el-tab-pane label="LoRA 适配器" name="adapters">
          <el-empty v-if="!adapters.length" description="还没有训练出的适配器" />
          <el-table v-else :data="adapters" stripe>
            <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
            <el-table-column label="基础模型" min-width="180">
              <template #default="{ row }">
                {{ row.baseModel.name }}
                <el-tag :type="compatOf(row).type" size="small">{{ compatOf(row).label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="来源" width="110">
              <template #default="{ row }">
                <el-tooltip v-if="row.source === 'remote'" :content="`${row.remote?.targetId || ''} · 任务 ${row.jobId}`" placement="top">
                  <el-tag type="warning" size="small">远程训练</el-tag>
                </el-tooltip>
                <el-tag v-else type="info" size="small">本机训练</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="方法 / 步数" width="130">
              <template #default="{ row }">{{ row.method.toUpperCase() }} · {{ row.training.steps }} 步</template>
            </el-table-column>
            <el-table-column label="训练 / 验证 loss" width="150">
              <template #default="{ row }">{{ lossText(row) }}</template>
            </el-table-column>
            <el-table-column label="样本" width="100">
              <template #default="{ row }">{{ row.dataset.chars }} 字</template>
            </el-table-column>
            <el-table-column prop="createdAt" label="创建时间" width="160" />
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :disabled="row.compat !== 'ok'" @click="goInfer(row.matchedBaseId, row.id)">推理测试</el-button>
                <el-button link type="primary" @click="adapterDetail = row">详情</el-button>
                <el-button link type="primary" @click="onRenameAdapter(row)">重命名</el-button>
                <el-button link type="danger" @click="onDeleteAdapter(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ======================= 推理测试 ======================= -->
        <el-tab-pane label="推理测试" name="infer">
          <div class="infer-load">
            <el-select v-model="infer.baseId" placeholder="基础模型" style="width: 240px" @change="infer.adapterId = ''">
              <el-option v-for="m in models.filter((x) => x.exists)" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>
            <el-select v-model="infer.adapterId" placeholder="不使用适配器（原始模型）" clearable style="width: 300px">
              <el-option label="不使用适配器（原始基础模型）" value="" />
              <el-option v-for="a in inferAdapters" :key="a.id" :label="`LoRA · ${a.name}`" :value="a.id">
                <span>LoRA · {{ a.name }}</span>
                <span class="opt-meta">{{ a.source === 'remote' ? '远程' : '本机' }} · {{ a.createdAt }}</span>
              </el-option>
            </el-select>
            <el-select v-model="infer.quantization" style="width: 150px">
              <el-option label="自动（推荐）" value="auto" />
              <el-option label="4-bit 量化" value="4bit" />
              <el-option label="不量化（16-bit）" value="none" />
            </el-select>
            <el-button type="primary" :loading="inferState?.status === 'loading'" :disabled="!infer.baseId || !!activeTrain" @click="onLoad">{{ loadLabel }}</el-button>
            <el-button :disabled="inferState?.status !== 'loaded' && inferState?.status !== 'error'" @click="onUnload">卸载</el-button>
          </div>
          <div v-if="selectedAdapter" class="adapter-info">
            <b>{{ selectedAdapter.name }}</b>
            <el-tag :type="compatOf(selectedAdapter).type" size="small">{{ compatOf(selectedAdapter).label }}</el-tag>
            <span>基础模型 {{ selectedAdapter.baseModel.name }}<template v-if="selectedAdapter.baseModel.revision">（revision {{ selectedAdapter.baseModel.revision.slice(0, 8) }}）</template></span>
            <span>{{ selectedAdapter.source === 'remote' ? `远程训练 · ${selectedAdapter.remote?.targetId || ''}` : '本机训练' }} · 任务 {{ selectedAdapter.jobId }}</span>
            <span>训练于 {{ selectedAdapter.createdAt }}<template v-if="selectedAdapter.metrics?.trainRuntime"> · 用时 {{ duration(Math.round(selectedAdapter.metrics.trainRuntime)) }}</template></span>
            <span>{{ selectedAdapter.method.toUpperCase() }} · {{ selectedAdapter.training.steps }} 步 · seq {{ selectedAdapter.training.maxSeqLen }} · {{ lossText(selectedAdapter) }}</span>
            <span>样本 {{ selectedAdapter.dataset.chars }} 字<template v-if="selectedAdapter.dataset.sources?.[0]">（{{ selectedAdapter.dataset.sources.map((s) => s.name).join('、') }}）</template></span>
          </div>
          <div class="infer-status">
            <template v-if="inferState?.status === 'loaded'">
              <el-tag type="success" size="small">已加载</el-tag>
              {{ modelName(inferState.baseId) }}
              <template v-if="inferState.adapterId"> + <el-tag type="warning" size="small">LoRA</el-tag> {{ adapterName(inferState.adapterId) }}</template>
              <template v-else-if="inferState.attachedAdapterId">（适配器 {{ adapterName(inferState.attachedAdapterId) }} 已挂载但停用 → 当前为原始基础模型）</template>
              <template v-else>（原始基础模型）</template>
              · {{ inferState.quantization }} · 用时 {{ inferState.loadSeconds }}s<template v-if="inferState.vramAllocatedGB != null"> · 显存 {{ inferState.vramAllocatedGB }} GB</template>
            </template>
            <template v-else-if="inferState?.status === 'loading'">
              <el-tag type="warning" size="small">加载中</el-tag>
              <template v-if="inferState.loadedAt"> 正在挂载适配器（基础模型保持驻留，不重新加载）</template>
              <template v-else> 首次加载需读取整个模型文件，可能需要 1~3 分钟</template>
            </template>
            <template v-else-if="inferState?.status === 'error'"><el-tag type="danger" size="small">加载失败</el-tag> {{ inferState.error }}</template>
            <template v-else><el-tag type="info" size="small">未加载</el-tag><span v-if="activeTrain"> 训练进行中，GPU 被占用</span></template>
            <span v-if="inferEstimate" :class="['est-inline', inferEstimate.level]">资源评估：{{ inferEstimate.messages.join('；') }}</span>
          </div>

          <el-input v-model="gen.prompt" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" placeholder="输入开头，模型将续写（风格微调后推荐用续写模式）" />
          <div class="gen-params">
            <el-radio-group v-model="gen.useChatTemplate" size="small">
              <el-radio-button :value="false">续写</el-radio-button>
              <el-radio-button :value="true">对话</el-radio-button>
            </el-radio-group>
            <span>最多生成 <el-input-number v-model="gen.maxNewTokens" :min="1" :max="1024" :step="50" size="small" /> tokens</span>
            <span>温度 <el-input-number v-model="gen.temperature" :min="0" :max="2" :step="0.1" :precision="1" size="small" /></span>
            <span>top_p <el-input-number v-model="gen.topP" :min="0.1" :max="1" :step="0.05" :precision="2" size="small" /></span>
            <span>种子 <el-input-number v-model="gen.seed" :min="0" :max="2147483647" :controls="false" size="small" style="width: 90px" /></span>
            <el-button type="primary" :icon="MagicStick" :loading="generating === 'single'" :disabled="inferState?.status !== 'loaded' || !gen.prompt.trim() || !!generating" @click="onGenerate">生成</el-button>
            <el-tooltip content="同一提示词、同一种子，依次用原始基础模型（停用适配器）和微调模型生成；基础模型只驻留一份" placement="top">
              <el-button type="warning" :loading="generating === 'compare'" :disabled="inferState?.status !== 'loaded' || !inferState?.attachedAdapterId || !gen.prompt.trim() || !!generating" @click="onCompare">对照生成（基础 vs 微调）</el-button>
            </el-tooltip>
            <el-tooltip content="把输入框里的文字当作评估文本（建议粘贴一两千字目标风格的原文），分别计算停用 / 启用适配器时的困惑度；越低说明模型越「像」这段文字" placement="top">
              <el-button :loading="generating === 'evaluate'" :disabled="inferState?.status !== 'loaded' || !inferState?.attachedAdapterId || gen.prompt.trim().length < 20 || !!generating" @click="onEvaluate">困惑度评估</el-button>
            </el-tooltip>
          </div>
          <div v-if="generating" class="hint">{{ generating === 'evaluate' ? '正在评估' : '正在生成' }}，{{ generating === 'compare' ? '对照需要生成两次，' : '' }}请稍候…</div>
          <el-alert v-if="evalResult" :type="evalResult.lossDelta < -0.05 ? 'success' : 'info'" :closable="false" show-icon class="gen-output"
            :title="`困惑度：基础模型 ${evalResult.base.ppl} → 微调模型 ${evalResult.adapter.ppl}（${evalResult.pplChangePct > 0 ? '+' : ''}${evalResult.pplChangePct}%，${evalResult.tokens} tokens）`"
            :description="evalResult.lossDelta < -0.05 ? '适配器让模型更贴近这段文字的风格。可再用一段风格无关的文字对照：差距小或变高，说明学到的是该风格本身' : '适配器对这段文字没有明显帮助：文字与训练风格不同，或适配器训练不足'" />
          <div v-if="genResult" class="gen-output">
            <div class="hint">{{ genResult.adapterId ? `微调模型（LoRA · ${adapterName(genResult.adapterId)}）` : '原始基础模型' }}</div>
            <div class="gen-text"><span class="gen-prompt">{{ genResult.prompt }}</span>{{ genResult.text }}</div>
            <div class="hint">{{ genStats(genResult) }}</div>
          </div>
          <div v-if="compareResult" class="compare-grid">
            <div v-for="side in ['base', 'adapter']" :key="side" class="gen-output">
              <div class="compare-title">
                <el-tag :type="side === 'base' ? 'info' : 'warning'" size="small">{{ side === 'base' ? '基础模型' : '微调模型' }}</el-tag>
                {{ side === 'base' ? modelName(compareResult.base.baseId) : `LoRA · ${adapterName(compareResult.adapter.adapterId)}` }}
              </div>
              <div class="gen-text"><span class="gen-prompt">{{ compareResult.prompt }}</span>{{ compareResult[side].text }}</div>
              <div class="hint">{{ genStats(compareResult[side]) }}</div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 登记本地模型 -->
    <el-dialog v-model="registerDlg.visible" title="登记本地模型" width="600px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="registerDlg.name" placeholder="如：Qwen2.5-1.5B-Instruct" /></el-form-item>
        <el-form-item label="目录">
          <el-input v-model="registerDlg.path" placeholder="包含 config.json 和 .safetensors 的文件夹路径" />
          <div class="hint">例如 D:\workplace\llama.cpp_cuda12-12.4\HuggingFac\Qwen2.5-1.5B-Instruct\Qwen2.5-1.5B-Instruct</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="registerDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="registerDlg.loading" @click="onRegister">登记</el-button>
      </template>
    </el-dialog>

    <!-- 下载模型 -->
    <el-dialog v-model="downloadDlg.visible" title="下载模型" width="660px">
      <div class="rec-list">
        <div v-for="r in RECOMMENDED_MODELS" :key="r.repoId" class="rec-item" :class="{ 'is-active': downloadDlg.repoId === r.repoId }" @click="pickRecommended(r)">
          <b>{{ r.repoId }}</b> <el-tag v-if="r.big" size="small" type="warning" effect="plain">大模型</el-tag>
          <span class="hint">{{ r.size }} · {{ r.note }}</span>
        </div>
      </div>
      <el-form label-width="80px" class="dl-form">
        <el-form-item label="仓库 ID"><el-input v-model="downloadDlg.repoId" placeholder="如 Qwen/Qwen2.5-0.5B-Instruct" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="downloadDlg.name" placeholder="留空则使用仓库名" /></el-form-item>
        <el-form-item label="下载源">
          <el-select v-model="downloadDlg.source" style="width: 200px">
            <el-option v-for="s in DOWNLOAD_SOURCES" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
          <span class="hint">{{ DOWNLOAD_SOURCES.find((s) => s.value === downloadDlg.source)?.note }}</span>
        </el-form-item>
        <el-form-item label="保存位置">
          <el-radio-group v-model="downloadDlg.where" @change="downloadDlg.check = null">
            <el-radio value="default">默认（python-service/models/base/，所在盘剩余 {{ cDiskFree }}）</el-radio>
            <el-radio value="custom">自选目录</el-radio>
          </el-radio-group>
          <div v-if="downloadDlg.where === 'custom'" class="dl-target">
            <el-input v-model="downloadDlg.targetDir" placeholder="如 D:\models（会新建 <仓库名> 子目录）" clearable @input="downloadDlg.check = null" />
            <el-button :icon="FolderOpened" @click="openDirPicker">浏览</el-button>
          </div>
        </el-form-item>
        <el-form-item label="空间检查">
          <el-button size="small" :loading="downloadDlg.checking" :disabled="!downloadDlg.repoId" @click="onCheckDownload">检查大小与剩余空间</el-button>
          <span v-if="downloadDlg.check" class="hint" :class="{ 'text-danger': !downloadDlg.check.enough }">
            {{ downloadDlg.check.sourceLabel }}：约 {{ downloadDlg.check.sizeGb }} GB → {{ downloadDlg.check.target }}，
            该盘剩余 {{ downloadDlg.check.freeGb }} GB{{ downloadDlg.check.enough ? '，足够' : '，空间不足（需另留 2 GB），请换个位置' }}
          </span>
        </el-form-item>
      </el-form>
      <el-alert v-if="isBigRepo" type="warning" :closable="false" show-icon class="dl-warn"
        title="7B 及以上模型约 15 GB：建议保存到空间充足的盘；本机 8GB 显存只能 4bit 推理（加载前先卸载其他模型），本机 QLoRA 训练会超出资源（可在远程 GPU 训练后加载适配器）" />
      <div class="hint">完成后自动登记；进度见「风格微调 → 任务记录」的日志。自选目录下载的模型在删除登记时会一并删除文件。</div>
      <template #footer>
        <el-button @click="downloadDlg.visible = false">取消</el-button>
        <el-button type="primary" :disabled="!downloadDlg.repoId || (downloadDlg.where === 'custom' && !downloadDlg.targetDir.trim())" @click="onDownload">开始下载</el-button>
      </template>
    </el-dialog>

    <!-- 选择保存位置 -->
    <el-dialog v-model="dirDlg.visible" title="选择保存位置" width="560px" append-to-body>
      <div class="dir-bar">
        <el-button size="small" :disabled="dirDlg.path === ''" @click="loadDirs(dirDlg.parent ?? '')">上一级</el-button>
        <span class="dir-path">{{ dirDlg.path || '此电脑' }}</span>
        <span v-if="dirDlg.freeGb != null" class="hint">剩余 {{ dirDlg.freeGb }} GB</span>
      </div>
      <div v-loading="dirDlg.loading" class="dir-list">
        <div v-for="d in dirDlg.dirs" :key="d.path" class="dir-item" @dblclick="loadDirs(d.path)" @click="loadDirs(d.path)">
          <el-icon><Folder /></el-icon>
          <span>{{ d.name }}</span>
          <span v-if="d.freeGb != null" class="hint">剩余 {{ d.freeGb }} GB</span>
        </div>
        <el-empty v-if="!dirDlg.loading && !dirDlg.dirs.length" description="没有子目录" :image-size="60" />
      </div>
      <template #footer>
        <el-button @click="dirDlg.visible = false">取消</el-button>
        <el-button type="primary" :disabled="!dirDlg.path" @click="chooseDir">选择「{{ dirDlg.path || '…' }}」</el-button>
      </template>
    </el-dialog>

    <!-- 任务日志 -->
    <el-drawer v-model="logDlg.visible" :title="`任务日志 · ${logDlg.job?.id || ''}`" size="55%" @closed="logDlg.job = null">
      <template v-if="logDlg.job">
        <el-alert v-if="logDlg.job.error" type="error" :closable="false" show-icon :title="logDlg.job.error" class="log-error" />
        <div v-if="logDlg.job.progress?.history?.length" class="loss-line">
          loss：<span v-for="h in logDlg.job.progress.history.slice(-30)" :key="h.step" class="loss-pt" :title="`step ${h.step}`">{{ h.loss }}</span>
        </div>
        <pre ref="logBox" class="log-box">{{ logDlg.text || '（暂无日志）' }}</pre>
      </template>
    </el-drawer>

    <!-- 适配器详情 -->
    <el-dialog :model-value="!!adapterDetail" :title="adapterDetail?.name" width="680px" @update:model-value="adapterDetail = null">
      <template v-if="adapterDetail">
        <div v-if="adapterDetail.sample?.text" class="sample-box">
          <div class="section-title">训练后续写示例</div>
          <div class="gen-text"><span class="gen-prompt">{{ adapterDetail.sample.prompt }}</span>{{ adapterDetail.sample.text }}</div>
        </div>
        <div class="section-title">元数据（基础模型指纹、训练配置、数据集）</div>
        <pre class="log-box">{{ JSON.stringify(adapterDetail, null, 2) }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onDeactivated, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Folder, FolderAdd, FolderOpened, MagicStick, Monitor, Refresh, VideoPlay } from '@element-plus/icons-vue'
import {
  DOWNLOAD_SOURCES, RECOMMENDED_MODELS, cancelJob, checkDownload, listDirs, compareGenerate, deleteAdapter, evaluateAdapter, deleteModel, downloadModel, estimate, generate, getInference,
  getJobLog, getSystem, listAdapters, listJobs, listModels, loadModel, registerModel, renameAdapter,
  startTraining, unloadModel
} from '@/api/localModel'
import { listFiles } from '@/api/file'
import { errorMessage } from '@/api/request'

const LOAD_STATUS = {
  idle: { label: '未加载', type: 'info' },
  loading: { label: '加载中', type: 'warning' },
  loaded: { label: '已加载', type: 'success' },
  error: { label: '加载失败', type: 'danger' }
}
const JOB_STATUS = {
  queued: { label: '排队中', type: 'info' },
  running: { label: '进行中', type: 'warning' },
  succeeded: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' }
}
const COMPAT = {
  ok: { label: '匹配', type: 'success' },
  changed: { label: '基础模型已变更', type: 'warning' },
  missing: { label: '基础模型缺失', type: 'danger' },
  unverified: { label: '权重未校验', type: 'warning' },
  'remote-only': { label: '本机无匹配基础模型', type: 'danger' }
}
const compatOf = (a) => COMPAT[a.compat] || { label: a.compat, type: 'info' }
const lossText = (a) => {
  const ev = a.evaluation || {}
  const val = ev.status === 'ok' ? ` · 验证 ${ev.evalLossBefore} → ${ev.evalLossAfter}` : ''
  return `训练 ${a.metrics?.finalLoss ?? '-'}${val}`
}
const genStats = (r) => `${r.newTokens} tokens · ${r.seconds}s · ${r.tokensPerSecond} tokens/s${r.seed != null ? ` · 种子 ${r.seed}` : ''}`
const EST_TYPE = { ok: 'success', warn: 'warning', exceed: 'error' }
const TEXT_EXTS = ['txt', 'md', 'docx', 'pdf']

const tab = ref('models')
const sys = ref(null)
const loadError = ref('')
const models = ref([])
const adapters = ref([])
const jobList = ref([])
const files = ref([])
const inferState = ref(null)

const textFiles = computed(() => files.value.filter((f) => TEXT_EXTS.includes((f.fileExt || '').toLowerCase())))
const activeJob = computed(() => jobList.value.find((j) => ['queued', 'running'].includes(j.status)))
const activeTrain = computed(() => activeJob.value?.kind === 'train')

const pct = (a, b) => (b ? Math.min(100, Math.round((a / b) * 100)) : 0)
const gb = (bytes) => `${(bytes / 1024 ** 3).toFixed(1)} GB`
const kb = (bytes) => (bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`)
const duration = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} 小时 ${Math.round((s % 3600) / 60)} 分` : s >= 60 ? `${Math.round(s / 60)} 分钟` : `${s} 秒`)
const modelName = (id) => models.value.find((m) => m.id === id)?.name || id
const adapterName = (id) => adapters.value.find((a) => a.id === id)?.name || id

/** 统一调用：code !== 0 时抛出 message */
async function call(promise, fallback) {
  try {
    const res = await promise
    if (res.code !== 0) throw new Error(res.message || fallback)
    return res.data
  } catch (e) {
    const err = new Error(errorMessage(e, fallback))
    err.data = e?.response?.data?.data
    err.status = e?.response?.status
    throw err
  }
}

async function refreshAll() {
  try {
    const [s, m, a, j] = await Promise.all([
      call(getSystem(), '获取系统状态失败'), call(listModels(), '获取模型失败'),
      call(listAdapters(), '获取适配器失败'), call(listJobs(), '获取任务失败')
    ])
    sys.value = s
    models.value = m
    adapters.value = a
    jobList.value = j
    inferState.value = s.inference
    loadError.value = ''
    if (!train.baseModelId && m.length) train.baseModelId = m.find((x) => x.exists)?.id || ''
    if (s.deps && !s.deps.qloraReady && train.method === 'qlora') train.method = 'lora'
  } catch (e) {
    loadError.value = `${e.message}（AI 服务地址见 VITE_AI_BASE_URL，请确认 python-service 已启动）`
  }
}

/* ---------------- 轮询：有任务进行中 / 模型加载中时刷新 ---------------- */
let timer = null
function schedule() {
  clearTimeout(timer)
  const busy = activeJob.value || inferState.value?.status === 'loading' || logDlg.visible
  timer = setTimeout(async () => {
    await refreshAll()
    if (logDlg.visible) await refreshLog()
    schedule()
  }, busy ? 3000 : 15000)
}

/* ---------------- 基础模型 ---------------- */
const registerDlg = reactive({ visible: false, name: '', path: '', loading: false })
async function onRegister() {
  if (!registerDlg.path.trim()) return ElMessage.warning('请填写模型目录')
  registerDlg.loading = true
  try {
    const name = registerDlg.name.trim() || registerDlg.path.trim().split(/[\\/]/).filter(Boolean).pop()
    const rec = await call(registerModel(name, registerDlg.path.trim()), '登记失败')
    ElMessage.success(`已登记「${rec.name}」（${(rec.numParams / 1e9).toFixed(2)}B）`)
    Object.assign(registerDlg, { visible: false, name: '', path: '' })
    refreshAll()
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    registerDlg.loading = false
  }
}

const DOWNLOAD_DIR_KEY = 'nan_novel.local.downloadDir'
const downloadDlg = reactive({
  visible: false, repoId: RECOMMENDED_MODELS[0].repoId, name: '', source: 'auto',
  where: 'default', targetDir: readDownloadDir(), check: null, checking: false
})
const isBigRepo = computed(() => /(^|[^\d.])([7-9]|[1-9]\d+)(\.\d+)?B/i.test(downloadDlg.repoId))
const cDiskFree = computed(() => (sys.value?.diskFreeGB != null ? `${sys.value.diskFreeGB.toFixed(1)} GB` : '未知'))

function readDownloadDir() {
  try {
    return localStorage.getItem(DOWNLOAD_DIR_KEY) || ''
  } catch {
    return ''
  }
}

function pickRecommended(r) {
  downloadDlg.repoId = r.repoId
  downloadDlg.check = null
  // 大模型默认放到自选目录（C 盘通常放不下）
  if (r.big && downloadDlg.where === 'default') downloadDlg.where = 'custom'
}

async function onCheckDownload() {
  downloadDlg.checking = true
  downloadDlg.check = null
  try {
    downloadDlg.check = await call(checkDownload(downloadDlg.repoId.trim(), downloadDlg.source,
      downloadDlg.where === 'custom' ? downloadDlg.targetDir.trim() : ''), '检查失败')
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 8000 })
  } finally {
    downloadDlg.checking = false
  }
}

const dirDlg = reactive({ visible: false, path: '', parent: null, freeGb: null, dirs: [], loading: false })
async function loadDirs(path) {
  dirDlg.loading = true
  try {
    const data = await call(listDirs(path), '读取目录失败')
    Object.assign(dirDlg, { path: data.path, parent: data.parent, freeGb: data.freeGb, dirs: data.dirs })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    dirDlg.loading = false
  }
}
function openDirPicker() {
  dirDlg.visible = true
  loadDirs(downloadDlg.targetDir.trim())
}
function chooseDir() {
  downloadDlg.targetDir = dirDlg.path
  downloadDlg.check = null
  dirDlg.visible = false
}

async function onDownload() {
  const targetDir = downloadDlg.where === 'custom' ? downloadDlg.targetDir.trim() : ''
  try {
    await call(downloadModel(downloadDlg.repoId.trim(), downloadDlg.name.trim(), downloadDlg.source, targetDir), '启动下载失败')
    if (targetDir) {
      try {
        localStorage.setItem(DOWNLOAD_DIR_KEY, targetDir)
      } catch {
        // 记不住也不影响下载
      }
    }
    ElMessage.success('已开始下载，可在「风格微调 → 任务记录」查看进度')
    downloadDlg.visible = false
    await refreshAll()
    schedule()
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  }
}

async function onDeleteModel(row) {
  const extra = row.managed ? `该模型由本服务下载（${row.path}），文件将一并删除。` : '只删除登记，不会删除原目录中的模型文件。'
  try {
    await ElMessageBox.confirm(`删除基础模型「${row.name}」？${extra}基于它训练的适配器会显示「基础模型缺失」。`, '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await call(deleteModel(row.id), '删除失败')
    ElMessage.success('已删除')
    refreshAll()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

/* ---------------- 风格微调 ---------------- */
const train = reactive({
  baseModelId: '', adapterName: '', method: 'qlora', sampleText: '', sampleFileIds: [],
  epochs: 3, learningRate: 0.0002, maxSeqLen: 512, batchSize: 1, gradAccum: 4, maxSteps: 0,
  loraR: 16, loraAlpha: 32, loraDropout: 0.05
})
const trainEstimate = ref(null)
const starting = ref(false)

let estTimer = null
watch(
  () => [train.baseModelId, train.method, train.maxSeqLen, train.batchSize, train.loraR],
  () => {
    clearTimeout(estTimer)
    if (!train.baseModelId) return (trainEstimate.value = null)
    estTimer = setTimeout(async () => {
      try {
        trainEstimate.value = await call(estimate({
          baseModelId: train.baseModelId, mode: 'train', quantization: train.method === 'qlora' ? '4bit' : 'none',
          maxSeqLen: train.maxSeqLen, batchSize: train.batchSize, loraR: train.loraR
        }), '评估失败')
      } catch {
        trainEstimate.value = null
      }
    }, 400)
  }
)

async function onStartTraining(force = false) {
  if (!train.baseModelId) return ElMessage.warning('请选择基础模型')
  if (!train.adapterName.trim()) return ElMessage.warning('请填写适配器名称')
  starting.value = true
  try {
    const { sampleFileIds, ...rest } = train
    const sampleFiles = sampleFileIds.map((id) => {
      const f = files.value.find((x) => x.id === id)
      return { id, ext: f.fileExt, name: f.fileName }
    })
    await call(startTraining({ ...rest, adapterName: train.adapterName.trim(), sampleFiles, force }), '启动训练失败')
    ElMessage.success('训练已开始')
    await refreshAll()
    schedule()
  } catch (e) {
    if (e.status === 409 && !force) {
      try {
        await ElMessageBox.confirm(`${e.message}\n\n仍要强制开始吗？可能因显存 / 内存不足而失败。`, '资源可能不足', {
          type: 'warning', confirmButtonText: '强制开始', cancelButtonText: '调整配置'
        })
        return onStartTraining(true)
      } catch {
        return
      }
    }
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    starting.value = false
  }
}

async function onCancelJob(row) {
  try {
    await call(cancelJob(row.id), '取消失败')
    ElMessage.info('已请求取消；训练会在当前步结束后停止')
    refreshAll()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const logDlg = reactive({ visible: false, job: null, text: '' })
const logBox = ref()
async function refreshLog() {
  if (!logDlg.job) return
  try {
    const id = logDlg.job.id
    const { log } = await call(getJobLog(id), '获取日志失败')
    logDlg.text = log
    logDlg.job = jobList.value.find((j) => j.id === id) || logDlg.job
    await nextTick()
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  } catch {
    /* 下次轮询重试 */
  }
}
async function openLog(row) {
  Object.assign(logDlg, { visible: true, job: row, text: '' })
  await refreshLog()
  schedule()
}

/* ---------------- 适配器 ---------------- */
const adapterDetail = ref(null)
async function onRenameAdapter(row) {
  let name
  try {
    ({ value: name } = await ElMessageBox.prompt('新名称', '重命名适配器', { inputValue: row.name }))
  } catch {
    return
  }
  try {
    await call(renameAdapter(row.id, name), '重命名失败')
    refreshAll()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
async function onDeleteAdapter(row) {
  try {
    await ElMessageBox.confirm(`删除适配器「${row.name}」？文件将从 models/adapters/ 中删除。`, '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await call(deleteAdapter(row.id), '删除失败')
    ElMessage.success('已删除')
    refreshAll()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

/* ---------------- 推理 ---------------- */
const infer = reactive({ baseId: '', adapterId: '', quantization: 'auto' })
const inferEstimate = ref(null)
// matchedBaseId：registry 校验出的可加载本地基础模型（远程训练的适配器按 config + 权重指纹匹配）
const inferAdapters = computed(() => adapters.value.filter((a) => a.compat === 'ok' && a.matchedBaseId === infer.baseId))
const selectedAdapter = computed(() => adapters.value.find((a) => a.id === infer.adapterId) || null)
const loadLabel = computed(() => {
  const s = inferState.value
  if (s?.status !== 'loaded' || s.baseId !== infer.baseId) return '加载'
  return (infer.adapterId || null) === (s.adapterId || null) ? '重新加载' : '切换'
})
// 资源评估随所选基础模型 / 适配器 / 量化，以及加载状态（加载完成、切换、卸载）刷新；序号防止旧请求覆盖新结果
let estimateSeq = 0
async function refreshInferEstimate() {
  const seq = ++estimateSeq
  if (!infer.baseId) {
    inferEstimate.value = null
    return
  }
  try {
    const q = infer.quantization === 'none' ? 'none' : sys.value?.deps.qloraReady ? '4bit' : 'none'
    const r = await call(estimate({ baseModelId: infer.baseId, mode: 'infer', quantization: q, adapterId: infer.adapterId || null }), '评估失败')
    if (seq === estimateSeq) inferEstimate.value = r
  } catch {
    if (seq === estimateSeq) inferEstimate.value = null // 评估失败不影响使用
  }
}
watch(() => [infer.baseId, infer.adapterId, infer.quantization], refreshInferEstimate)
watch(() => [inferState.value?.status, inferState.value?.baseId, inferState.value?.adapterId, inferState.value?.attachedAdapterId],
  (cur, prev) => { if (String(cur) !== String(prev) && cur[0] !== 'loading') refreshInferEstimate() })

function goInfer(baseId, adapterId = '') {
  infer.baseId = baseId
  nextTick(() => (infer.adapterId = adapterId))
  tab.value = 'infer'
}
function goTrain(baseId) {
  train.baseModelId = baseId
  tab.value = 'train'
}

async function onLoad() {
  try {
    const s = await call(loadModel(infer.baseId, infer.adapterId || null, infer.quantization), '加载失败')
    inferState.value = s
    if (s.switched && s.status === 'loaded') ElMessage.success(s.adapterId ? '已启用适配器（未重新加载基础模型）' : '已切换为原始基础模型（适配器保持挂载、已停用）')
    schedule()
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  }
}
async function onUnload() {
  try {
    inferState.value = await call(unloadModel(), '卸载失败')
    refreshAll()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const gen = reactive({ prompt: '', maxNewTokens: 200, temperature: 0.8, topP: 0.9, useChatTemplate: false, seed: 1234 })
const generating = ref('') // '' | 'single' | 'compare' | 'evaluate'
const genResult = ref(null)
const compareResult = ref(null)
const evalResult = ref(null)
async function onGenerate() {
  generating.value = 'single'
  try {
    const r = await call(generate({ ...gen, repetitionPenalty: 1.1 }), '生成失败')
    genResult.value = { ...r, prompt: gen.useChatTemplate ? '' : gen.prompt }
    compareResult.value = null
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    generating.value = ''
  }
}
async function onCompare() {
  generating.value = 'compare'
  try {
    const r = await call(compareGenerate({ ...gen, repetitionPenalty: 1.1 }), '对照生成失败')
    compareResult.value = { ...r, prompt: gen.useChatTemplate ? '' : gen.prompt }
    genResult.value = null
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    generating.value = ''
  }
}
async function onEvaluate() {
  generating.value = 'evaluate'
  try {
    evalResult.value = await call(evaluateAdapter({ text: gen.prompt }), '评估失败')
  } catch (e) {
    ElMessage.error({ message: e.message, duration: 6000 })
  } finally {
    generating.value = ''
  }
}

/* ---------------- 生命周期 ---------------- */
onActivated(async () => {
  await refreshAll()
  listFiles().then((res) => { if (res.code === 0) files.value = res.data || [] }).catch(() => {})
  schedule()
})
onDeactivated(() => clearTimeout(timer))
</script>

<style scoped>
.box-card {
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.sys-card {
  margin-bottom: 16px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.sys-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: #606266;
}
.sys-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.sys-bar {
  width: 90px;
}
.sys-refresh {
  margin-left: auto;
}
.sys-alert {
  margin-top: 12px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.toolbar-hint,
.hint {
  font-size: 12px;
  color: #909399;
}
.hint {
  margin-left: 8px;
}
.train-form {
  max-width: 980px;
}
.samples {
  width: 100%;
  max-width: 760px;
}
.samples-files {
  margin-top: 8px;
}
.samples .hint {
  margin-left: 0;
}
.adv {
  margin: 0 0 18px 110px;
  max-width: 760px;
}
.adv-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
}
.section-title {
  margin: 18px 0 8px;
  font-weight: 600;
  color: #303133;
}
.job-error {
  display: block;
  font-size: 12px;
  color: var(--el-color-danger);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.infer-load,
.gen-params {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 13px;
  color: #606266;
}
.gen-params {
  margin-top: 10px;
}
.infer-status {
  margin-bottom: 12px;
  font-size: 13px;
  color: #606266;
}
.est-inline {
  display: block;
  margin-top: 4px;
  font-size: 12px;
}
.est-inline.ok {
  color: var(--el-color-success);
}
.est-inline.warn {
  color: var(--el-color-warning);
}
.est-inline.exceed {
  color: var(--el-color-danger);
}
.gen-output,
.sample-box {
  margin-top: 12px;
}
.compare-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}
.compare-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 13px;
}
.adapter-info {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 14px;
  margin: 8px 0 0;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.opt-meta {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.gen-text {
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
  background: #f7f8fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}
.gen-prompt {
  color: #909399;
}
.rec-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.rec-item {
  padding: 8px 12px;
  font-size: 13px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: pointer;
}
.rec-item.is-active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.dl-target {
  display: flex;
  gap: 8px;
  width: 100%;
  margin-top: 6px;
}
.dl-warn {
  margin-bottom: 8px;
}
.text-danger {
  color: var(--el-color-danger);
}
.dir-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.dir-path {
  font-family: Consolas, monospace;
  font-size: 13px;
  word-break: break-all;
}
.dir-list {
  height: 320px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.dir-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  font-size: 13px;
  cursor: pointer;
}
.dir-item:hover {
  background: var(--el-color-primary-light-9);
}
.log-error {
  margin-bottom: 10px;
  white-space: pre-wrap;
}
.loss-line {
  margin-bottom: 8px;
  font-size: 12px;
  color: #606266;
}
.loss-pt {
  display: inline-block;
  margin-right: 6px;
}
.log-box {
  max-height: 70vh;
  margin: 0;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
}
</style>
