/*
 * 通用显示菜单是 Application 层的交互编排中心：菜单项只发起业务请求，
 * 采集、输出和输入仍由对应模块异步完成；本任务按状态渲染当前页面。
 */
#include "application/menu/display_menu/display_menu.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "FreeRTOS.h"
#include "task.h"

#include "application/app_config.h"
#include "application/menu/custom_page/custom_page.h"
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
#include "application/waveform/waveform_measurement/waveform_measurement.h"
#include "modules/fft/fft_analysis.h"
#endif
#if APP_ENABLE_WAVEFORM_MAPPING != 0U
#include "application/waveform/waveform_mapping/waveform_mapping.h"
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
#include "application/waveform/waveform_output/waveform_output.h"
#endif
#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
#include "application/waveform/arbitrary_waveform/arbitrary_waveform.h"
#endif
#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
#include "application/waveform/pa27_threshold_trigger/pa27_threshold_trigger.h"
#endif
#include "application/communication/serial_communication/serial_communication.h"
#include "application/task/task_manager.h"
#include "modules/button/button.h"
#include "modules/display/display.h"
#include "modules/menu/menu.h"
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
#include "modules/pwm/pwm_output.h"
#endif
#include "modules/waveform/waveform.h"

/* 菜单轮询节拍、页面布局和异步结果缓冲容量均集中定义在此处。 */
#define DISPLAY_MENU_POLL_PERIOD_MS   (10UL)
#define DISPLAY_MENU_DEFAULT_CONTRAST (0xCFU)
#define DISPLAY_MENU_CONTRAST_STEP    (0x08U)
#define DISPLAY_MENU_CONTRAST_REPEAT_PERIOD_MS (80UL)
#define DISPLAY_MENU_ACTION_FEEDBACK_PERIOD_MS (700UL)
#define DISPLAY_MENU_STACK_DIAGNOSTIC_PERIOD_MS (1000UL)
#define DISPLAY_MENU_WAVEFORM_FIRST_PAGE      (1U)
#define DISPLAY_MENU_WAVEFORM_PAGE_COUNT      (7U)
#define DISPLAY_MENU_WAVEFORM_RANGE_COUNT     (4U)
#define DISPLAY_MENU_UART2_WAVEFORM_FRAME_SAMPLE_COUNT (1024U)
#define DISPLAY_MENU_UART3_WAVEFORM_FRAME_SAMPLE_COUNT \
    (APP_UART3_WAVEFORM_SAMPLE_COUNT)
#define DISPLAY_MENU_SPECTRUM_PLOT_Y           (16U)
#define DISPLAY_MENU_SPECTRUM_PLOT_HEIGHT \
    (DISPLAY_HEIGHT - DISPLAY_MENU_SPECTRUM_PLOT_Y)
#if APP_FFT_REMOVE_DC == 0U
/* 保留直流时将 bin 0 作为最左侧频谱柱显示。 */
#define DISPLAY_MENU_SPECTRUM_FIRST_BIN        (0U)
#else
/* 去直流时保持原布局，从第一个交流频带开始显示。 */
#define DISPLAY_MENU_SPECTRUM_FIRST_BIN        (1U)
#endif
#define DISPLAY_MENU_SPECTRUM_BAR_COUNT        (32U)
#define DISPLAY_MENU_SPECTRUM_BAR_WIDTH        (4U)
#define DISPLAY_MENU_SPECTRUM_COMPONENT_ROWS   (3U)
#define DISPLAY_MENU_UART3_TEXT_LINE_COUNT      (15U)
#define DISPLAY_MENU_UART3_TEXT_LINE_LENGTH     (20U)
#define DISPLAY_MENU_UART3_TEXT_VISIBLE_LINES   (5U)
#define DISPLAY_MENU_UART3_TEXT_TIMEOUT_MS      (5000UL)

/* 波形页可在本地 ADC 与两个外部串口来源之间循环切换。 */
typedef enum {
    DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA27 = 0,
    DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21,
    DISPLAY_MENU_WAVEFORM_SOURCE_UART2,
    DISPLAY_MENU_WAVEFORM_SOURCE_UART3,
    DISPLAY_MENU_WAVEFORM_SOURCE_COUNT
} DisplayMenuWaveformSource_e;

/* 长按调节对比度时记录当前自动重复方向。 */
typedef enum {
    DISPLAY_MENU_CONTRAST_REPEAT_NONE = 0,
    DISPLAY_MENU_CONTRAST_REPEAT_UP,
    DISPLAY_MENU_CONTRAST_REPEAT_DOWN
} DisplayMenuContrastRepeatDirection_e;

/* 记录功能页退出后应回到普通菜单还是电赛自定义页。 */
typedef enum {
    DISPLAY_MENU_RETURN_MAIN_MENU = 0,
    DISPLAY_MENU_RETURN_CUSTOM_PAGE
} DisplayMenuReturnTarget_e;

#if APP_ENABLE_UART3 != 0U
/* UART3 普通文本命令页的本地等待和显示状态。 */
typedef enum {
    DISPLAY_MENU_UART3_TEXT_IDLE = 0,
    DISPLAY_MENU_UART3_TEXT_WAIT,
    DISPLAY_MENU_UART3_TEXT_RX,
    DISPLAY_MENU_UART3_TEXT_ERROR,
    DISPLAY_MENU_UART3_TEXT_TIMEOUT
} DisplayMenuUART3TextStatus_e;

/*
 * 一项文本菜单命令包含显示标题、完整命令文本及可选的二阶段参数握手。
 * command/argument 字符串自身包含协议要求的行结束符。
 */
typedef struct {
    const char *label;
    const char *command;
    const char *prompt;
    const char *argument;
} DisplayMenuUART3Command;
#endif

/*
 * 显示菜单调试信息开关：
 * 1U：通过 UART0 输出菜单初始化状态。
 * 0U：只关闭本文件产生的提示，不影响菜单和按键。
 */
#define DISPLAY_MENU_DEBUG_OUTPUT_ENABLED (1U)

/* 显示、菜单、按键和波形绘制实例只在初始化时绑定，之后由菜单任务独占使用。 */
static DisplayInstance *menu_display;
static MenuInstance *menu;
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
static WaveformInstance *waveform;
#endif
static ButtonInstance *next_button;
static ButtonInstance *previous_button;
static uint8_t display_contrast = DISPLAY_MENU_DEFAULT_CONTRAST;
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
/* 当前波形页面的来源、量程和生命周期状态。 */
static bool waveform_active;
static DisplayMenuWaveformSource_e waveform_source;
static uint8_t waveform_range_index = 1U;
#if APP_ENABLE_UART3 != 0U
/* 菜单上下文直接指向此静态表项，表和元素在固件运行期间始终有效。 */
static SerialCommunicationUART3DataType_e uart3_curve_data_type =
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1;
static SerialCommunicationUART3DataType_e uart3_curve_data_types[] = {
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A3,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B1,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B3,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_1,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_3,
    SERIAL_COMMUNICATION_UART3_DATA_LAFC,
    SERIAL_COMMUNICATION_UART3_DATA_LPFC,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_A1,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_A3,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_B1,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_B3,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_1,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_3,
    SERIAL_COMMUNICATION_UART3_DATA_AFC,
    SERIAL_COMMUNICATION_UART3_DATA_PFC
};
/*
 * UART3 RX 任务写入文本行和 dirty 标志，显示任务消费参数请求并刷新页面；
 * 行缓冲、计数和跨任务标志通过短临界区成组更新或取得快照。
 */
static bool uart3_text_active;
static bool uart3_text_dirty;
static bool uart3_text_argument_pending;
static bool uart3_text_argument_sent;
static const DisplayMenuUART3Command *uart3_text_command;
static DisplayMenuUART3TextStatus_e uart3_text_status =
    DISPLAY_MENU_UART3_TEXT_IDLE;
static TickType_t uart3_text_deadline;
static char uart3_text_lines[DISPLAY_MENU_UART3_TEXT_LINE_COUNT]
    [DISPLAY_MENU_UART3_TEXT_LINE_LENGTH + 1U];
static uint8_t uart3_text_line_count;
static uint8_t uart3_text_page;
#endif
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
/*
 * UART3 保存完整 128 点；UART2 将同一数组作为最后 128 点环形缓冲。
 * 串口回调只写缓冲和完成标志，真正装载 Waveform 并刷屏由菜单任务执行。
 */
static int16_t waveform_frame_samples[
    DISPLAY_MENU_UART3_WAVEFORM_FRAME_SAMPLE_COUNT];
static size_t waveform_frame_sample_count;
static size_t waveform_frame_write_index;
static bool waveform_frame_collecting;
static bool waveform_frame_ready;
static bool waveform_frame_failed;
static bool waveform_frame_timed_out;
#endif
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
#define DISPLAY_MENU_ADC_COPY_CHUNK_SIZE (64U)
/* ADC 页面只保存结果序号和小块搬运缓冲，不在显示任务栈上复制整帧。 */
static uint16_t waveform_adc_buffer[DISPLAY_MENU_ADC_COPY_CHUNK_SIZE];
static uint32_t waveform_adc_result_sequence = UINT32_MAX;
static bool waveform_adc_request_active;
static bool waveform_adc_request_failed;
static WaveformMeasurementRequestStatus_e
    waveform_adc_request_failure_status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
/* 频谱页持有一份静态结果，并用序号区分本次请求与进入页面前的旧结果。 */
static bool spectrum_active;
#if APP_ENABLE_WAVEFORM_PA27 != 0U
static FFTAnalysisInput_e spectrum_input = FFT_ANALYSIS_INPUT_PA27;
#elif APP_ENABLE_WAVEFORM_PA21 != 0U
static FFTAnalysisInput_e spectrum_input = FFT_ANALYSIS_INPUT_PA21;
#elif APP_ENABLE_UART2 != 0U
static FFTAnalysisInput_e spectrum_input = FFT_ANALYSIS_INPUT_UART2;
#else
static FFTAnalysisInput_e spectrum_input = FFT_ANALYSIS_INPUT_UART3;
#endif
static FFTAnalysisResult spectrum_result;
static uint32_t spectrum_result_sequence = UINT32_MAX;
static uint32_t spectrum_previous_sequence = UINT32_MAX;
static bool spectrum_request_active;
static bool spectrum_request_failed;
static bool spectrum_components_active;
static uint8_t spectrum_component_page;
#if APP_ENABLE_UART3_SPECTRUM != 0U
static SerialCommunicationUART3DataType_e uart3_spectrum_data_type =
    SERIAL_COMMUNICATION_UART3_DATA_LSPECT_A;
static SerialCommunicationUART3DataType_e uart3_spectrum_data_types[] = {
    SERIAL_COMMUNICATION_UART3_DATA_LSPECT_A,
    SERIAL_COMMUNICATION_UART3_DATA_LSPECT_B,
    SERIAL_COMMUNICATION_UART3_DATA_SPECT_A,
    SERIAL_COMMUNICATION_UART3_DATA_SPECT_B,
    SERIAL_COMMUNICATION_UART3_DATA_SPECTRUM
};
#endif
static WaveformMeasurementRequestStatus_e
    spectrum_request_failure_status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
/* 双路相位页面与普通频谱页面互斥显示，但共用测量任务的异步完成机制。 */
static bool phase_active;
static WaveformSynchronizedPhaseMeasurement phase_result;
static uint32_t phase_previous_sequence = UINT32_MAX;
static bool phase_request_active;
static bool phase_request_failed;
static WaveformMeasurementRequestStatus_e
    phase_request_failure_status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;
#endif
#endif
/* 页面导航、动作反馈和栈诊断均由唯一显示任务推进。 */
static DisplayMenuContrastRepeatDirection_e contrast_repeat_direction;
static uint32_t contrast_repeat_elapsed_ms;
static bool action_feedback_active;
static bool action_feedback_success;
static const char *action_feedback_label;
static uint32_t action_feedback_elapsed_ms;
static bool custom_page_active;
static DisplayMenuReturnTarget_e display_menu_return_target =
    DISPLAY_MENU_RETURN_MAIN_MENU;
static size_t display_menu_return_depth;
static bool display_menu_task_created;
static uint32_t display_menu_stack_diagnostic_elapsed_ms;
static volatile uint32_t display_menu_minimum_free_stack_words;

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
static const int16_t waveform_ranges[DISPLAY_MENU_WAVEFORM_RANGE_COUNT] = {
    500, 1000, 2000, 4000
};

static const char *const waveform_range_labels[
    DISPLAY_MENU_WAVEFORM_RANGE_COUNT] = {
    "R500", "R1K", "R2K", "R4K"
};
#endif

static void DisplayMenuTask(void *argument);
static bool DisplayMenuOpenMenuPageFromCustom(
    const MenuPage *target_page);
static void DisplayMenuReturnFromCurrentPage(void);
static void DisplayMenuDebugSend(const uint8_t *data, size_t size);
#if APP_ENABLE_UART2 != 0U
static void DisplayMenuUART2SampleReceived(
    int16_t sample, void *context);
#endif
#if APP_ENABLE_UART3 != 0U
static void DisplayMenuUART3SampleReceived(
    int16_t sample, void *context);
static bool DisplayMenuUART3LineReceived(
    const uint8_t *data, size_t size, void *context);
static void DisplayMenuActionStartUART3Command(void *context);
static bool DisplayMenuStartUART3Command(
    const DisplayMenuUART3Command *command);
static bool DisplayMenuSendUART3CommandText(const char *text);
static void DisplayMenuProcessUART3TextPage(
    Button_Event_e next_event, Button_Event_e previous_event);
static bool DisplayMenuRenderUART3TextPage(void);
static bool DisplayMenuUART3TextContains(
    const uint8_t *data, size_t size, const char *fragment);
#endif
static void DisplayMenuActionNormal(void *context);
static void DisplayMenuActionInvert(void *context);
static void DisplayMenuActionContrastUp(void *context);
static void DisplayMenuActionContrastDown(void *context);
static void DisplayMenuAdjustContrast(bool increase);
static void DisplayMenuProcessContrastRepeat(void);
static void DisplayMenuSetActionFeedback(
    const char *label, bool success);
static void DisplayMenuProcessActionFeedback(void);
static bool DisplayMenuRenderActionFeedback(void);
static void DisplayMenuActionStartCustomPage(void *context);
static void DisplayMenuActionResetDisplay(void *context);
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 != 0U)
static void DisplayMenuActionStartADC27Waveform(void *context);
#endif
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
static void DisplayMenuActionStartADC21Waveform(void *context);
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
static bool DisplayMenuRequestADCMeasurement(
    WaveformMeasurementInput_e input,
    DisplayMenuWaveformSource_e source, bool start_page);
static bool DisplayMenuLoadADCWaveformSamples(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement);
#endif
#if APP_ENABLE_UART2 != 0U
static void DisplayMenuActionStartUART2Waveform(void *context);
#endif
#if APP_ENABLE_UART3 != 0U
static void DisplayMenuActionStartUART3Waveform(void *context);
static const char *DisplayMenuGetUART3CurveLabel(void);
#endif
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U)
static void DisplayMenuActionStopDAC(void *context);
static void DisplayMenuActionSetDACDC(void *context);
static void DisplayMenuActionSetDACLowerLimit(void *context);
static void DisplayMenuActionSetDACUpperLimit(void *context);
static void DisplayMenuActionSetDACWaveform(void *context);
static bool DisplayMenuApplyDACLimits(
    WaveformOutputDACConfig *config);
static bool DisplayMenuSetDACLimits(
    uint16_t minimum_millivolts, uint16_t maximum_millivolts);
#endif
#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
static void DisplayMenuActionStartArbitraryWaveform(void *context);
static void DisplayMenuActionStopArbitraryWaveform(void *context);
#endif
#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
static void DisplayMenuActionSetPA27TriggerMode(void *context);
#endif
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
static void DisplayMenuActionStartPWM(void *context);
static void DisplayMenuActionStopPWM(void *context);
static void DisplayMenuActionSetPWMFrequency(void *context);
static void DisplayMenuActionSetPWMDutyCycle(void *context);
#endif
#if APP_ENABLE_WAVEFORM_MAPPING != 0U
static void DisplayMenuActionRequestWaveformMapping(void *context);
static void DisplayMenuActionStopWaveformMapping(void *context);
#endif
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U)
static void DisplayMenuActionStartDDS(void *context);
static void DisplayMenuActionStopDDS(void *context);
static void DisplayMenuActionSetDDSWaveform(void *context);
static void DisplayMenuActionSetDDSFrequency(void *context);
static void DisplayMenuActionSetDDSPhase(void *context);
#endif
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)
static void DisplayMenuActionStartAD9850(void *context);
static void DisplayMenuActionStopAD9850(void *context);
static void DisplayMenuActionSetAD9850Waveform(void *context);
static void DisplayMenuActionSetAD9850Frequency(void *context);
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
#if APP_ENABLE_WAVEFORM_PA27 != 0U
static void DisplayMenuActionStartFFT27(void *context);
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
static void DisplayMenuActionStartFFT21(void *context);
#endif
#if APP_ENABLE_UART2 != 0U
static void DisplayMenuActionStartFFTUART2(void *context);
#endif
#if APP_ENABLE_UART3_SPECTRUM != 0U
static void DisplayMenuActionStartFFTUART3(void *context);
#endif
static const char *DisplayMenuGetUART3SpectrumLabel(void);
static void DisplayMenuStartSpectrum(FFTAnalysisInput_e input);
static bool DisplayMenuRequestSpectrumMeasurement(
    FFTAnalysisInput_e input, bool prepare_uart3);
static void DisplayMenuHandleSpectrumButtons(Button_Event_e next_event,
    Button_Event_e previous_event);
static bool DisplayMenuProcessSpectrum(void);
static bool DisplayMenuRenderSpectrum(void);
static bool DisplayMenuRenderSpectrumComponents(void);
static void DisplayMenuFormatFrequency(
    uint32_t frequency_millihz, char prefix,
    char *buffer, size_t capacity);
static void DisplayMenuFormatAmplitudeMillivolts(
    uint16_t amplitude_millivolts, char *buffer, size_t capacity);
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
static void DisplayMenuActionStartSynchronizedPhase(void *context);
static bool DisplayMenuRequestSynchronizedPhase(void);
static void DisplayMenuHandlePhaseButtons(Button_Event_e left_event,
    Button_Event_e right_event);
static bool DisplayMenuProcessSynchronizedPhase(void);
static bool DisplayMenuRenderSynchronizedPhase(void);
static void DisplayMenuFormatPhase(
    int32_t phase_millidegrees, char *buffer, size_t capacity);
#endif
#endif
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
static void DisplayMenuStartWaveform(DisplayMenuWaveformSource_e source);
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
static bool DisplayMenuSubmitWaveformSampleForSource(
    DisplayMenuWaveformSource_e source, int16_t sample);
static void DisplayMenuStartWaveformFrameCollection(bool prepare_uart3);
static bool DisplayMenuLoadCompletedSerialFrame(void);
static size_t DisplayMenuGetSerialWaveformSampleCount(
    DisplayMenuWaveformSource_e source);
#endif
static void DisplayMenuHandleWaveformButtons(Button_Event_e next_event,
    Button_Event_e previous_event);
static void DisplayMenuProcessWaveform(void);
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
static bool DisplayMenuIsADCWaveformSource(DisplayMenuWaveformSource_e source);
#endif
static bool DisplayMenuRenderWaveform(bool update_header);
static void DisplayMenuChangeWaveformRange(bool next_range);
static void DisplayMenuSwitchWaveformSource(void);
static bool DisplayMenuIsWaveformSourceEnabled(
    DisplayMenuWaveformSource_e source);
static const char *DisplayMenuGetWaveformSourceLabel(void);
static const char *DisplayMenuGetWaveformFrameLabel(void);
#endif

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
static const MenuItem waveform_items[] = {
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 != 0U)
    {"ADC PA27", NULL, DisplayMenuActionStartADC27Waveform, NULL},
#endif
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
    {"ADC PB19", NULL, DisplayMenuActionStartADC21Waveform, NULL},
#endif
#if APP_ENABLE_UART2 != 0U
    {"UART2 PB16", NULL, DisplayMenuActionStartUART2Waveform, NULL},
#endif
#if APP_ENABLE_UART3 != 0U
    {"UART3 LWAVE A1", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[0]},
    {"UART3 LWAVE A3", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[1]},
    {"UART3 LWAVE B1", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[2]},
    {"UART3 LWAVE B3", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[3]},
    {"UART3 LWAVE 1", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[4]},
    {"UART3 LWAVE 3", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[5]},
    {"UART3 LAFC", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[6]},
    {"UART3 LPFC", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[7]},
    {"UART3 WAVE A1", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[8]},
    {"UART3 WAVE A3", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[9]},
    {"UART3 WAVE B1", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[10]},
    {"UART3 WAVE B3", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[11]},
    {"UART3 WAVE 1", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[12]},
    {"UART3 WAVE 3", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[13]},
    {"UART3 AFC", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[14]},
    {"UART3 PFC", NULL, DisplayMenuActionStartUART3Waveform,
        (void *)&uart3_curve_data_types[15]},
#endif
};

static const MenuPage waveform_page = {
    "WAVEFORM",
    waveform_items,
    sizeof(waveform_items) / sizeof(waveform_items[0])
};
#endif

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
static const MenuItem fft_spectrum_items[] = {
#if APP_ENABLE_WAVEFORM_PA27 != 0U
    {"FFT PA27", NULL, DisplayMenuActionStartFFT27, NULL},
#endif
#if APP_ENABLE_WAVEFORM_PA21 != 0U
    {"FFT PB19", NULL, DisplayMenuActionStartFFT21, NULL},
#endif
#if APP_ENABLE_UART2 != 0U
    {"FFT UART2", NULL, DisplayMenuActionStartFFTUART2, NULL},
#endif
#if APP_ENABLE_UART3_SPECTRUM != 0U
    {"UART3 LSPECT A", NULL, DisplayMenuActionStartFFTUART3,
        (void *)&uart3_spectrum_data_types[0]},
    {"UART3 LSPECT B", NULL, DisplayMenuActionStartFFTUART3,
        (void *)&uart3_spectrum_data_types[1]},
    {"UART3 SPECT A", NULL, DisplayMenuActionStartFFTUART3,
        (void *)&uart3_spectrum_data_types[2]},
    {"UART3 SPECT B", NULL, DisplayMenuActionStartFFTUART3,
        (void *)&uart3_spectrum_data_types[3]},
    {"UART3 SPECTRUM", NULL, DisplayMenuActionStartFFTUART3,
        (void *)&uart3_spectrum_data_types[4]},
#endif
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
    {"PHASE PAIR", NULL,
        DisplayMenuActionStartSynchronizedPhase, NULL}
#endif
};

static const MenuPage fft_spectrum_page = {
    "FFT SPECTRUM",
    fft_spectrum_items,
    sizeof(fft_spectrum_items) / sizeof(fft_spectrum_items[0])
};
#endif

#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U)
#define DISPLAY_MENU_DAC_DEFAULT_MINIMUM_MILLIVOLTS (500U)
#define DISPLAY_MENU_DAC_DEFAULT_MAXIMUM_MILLIVOLTS (2800U)

/* DAC 直流档位使用毫伏值作为菜单动作上下文。 */
static uint16_t dac_dc_levels_millivolts[] = {
    500U, 1000U, 1650U, 2500U, 3000U
};

static const MenuItem dac_dc_items[] = {
    {"0.50V", NULL, DisplayMenuActionSetDACDC,
        &dac_dc_levels_millivolts[0]},
    {"1.00V", NULL, DisplayMenuActionSetDACDC,
        &dac_dc_levels_millivolts[1]},
    {"1.65V", NULL, DisplayMenuActionSetDACDC,
        &dac_dc_levels_millivolts[2]},
    {"2.50V", NULL, DisplayMenuActionSetDACDC,
        &dac_dc_levels_millivolts[3]},
    {"3.00V", NULL, DisplayMenuActionSetDACDC,
        &dac_dc_levels_millivolts[4]}
};

static const MenuPage dac_dc_page = {
    "DAC DC LEVEL",
    dac_dc_items,
    sizeof(dac_dc_items) / sizeof(dac_dc_items[0])
};

/* 周期波形的上下限可分别设置，但必须保持下限小于上限。 */
static uint16_t dac_limit_levels_millivolts[] = {
    0U, 500U, 1000U, 1500U, 2000U,
    2500U, 2800U, 3000U, 3300U
};
static uint16_t dac_selected_minimum_millivolts =
    DISPLAY_MENU_DAC_DEFAULT_MINIMUM_MILLIVOLTS;
static uint16_t dac_selected_maximum_millivolts =
    DISPLAY_MENU_DAC_DEFAULT_MAXIMUM_MILLIVOLTS;

#define DISPLAY_MENU_DAC_LIMIT_ITEMS(action) \
    {"0.00 V", NULL, action, &dac_limit_levels_millivolts[0]}, \
    {"0.50 V", NULL, action, &dac_limit_levels_millivolts[1]}, \
    {"1.00 V", NULL, action, &dac_limit_levels_millivolts[2]}, \
    {"1.50 V", NULL, action, &dac_limit_levels_millivolts[3]}, \
    {"2.00 V", NULL, action, &dac_limit_levels_millivolts[4]}, \
    {"2.50 V", NULL, action, &dac_limit_levels_millivolts[5]}, \
    {"2.80 V", NULL, action, &dac_limit_levels_millivolts[6]}, \
    {"3.00 V", NULL, action, &dac_limit_levels_millivolts[7]}, \
    {"3.30 V", NULL, action, &dac_limit_levels_millivolts[8]}

static const MenuItem dac_lower_limit_items[] = {
    DISPLAY_MENU_DAC_LIMIT_ITEMS(DisplayMenuActionSetDACLowerLimit)
};

static const MenuPage dac_lower_limit_page = {
    "DAC LOWER LIMIT",
    dac_lower_limit_items,
    sizeof(dac_lower_limit_items) / sizeof(dac_lower_limit_items[0])
};

static const MenuItem dac_upper_limit_items[] = {
    DISPLAY_MENU_DAC_LIMIT_ITEMS(DisplayMenuActionSetDACUpperLimit)
};

static const MenuPage dac_upper_limit_page = {
    "DAC UPPER LIMIT",
    dac_upper_limit_items,
    sizeof(dac_upper_limit_items) / sizeof(dac_upper_limit_items[0])
};

#undef DISPLAY_MENU_DAC_LIMIT_ITEMS

/* 模板保留原默认上下限，输出前会应用当前菜单选择。 */
#define DISPLAY_MENU_DAC_CONFIGS(mode_value) \
    {mode_value, 1U, 500U, 2800U},       \
    {mode_value, 10U, 500U, 2800U},      \
    {mode_value, 100U, 500U, 2800U},     \
    {mode_value, 1000U, 500U, 2800U},    \
    {mode_value, 5000U, 500U, 2800U},    \
    {mode_value, 10000U, 500U, 2800U},   \
    {mode_value, 20000U, 500U, 2800U},   \
    {mode_value, 31250U, 500U, 2800U},   \
    {mode_value, 62500U, 500U, 2800U}

static WaveformOutputDACConfig dac_sine_configs[] = {
    DISPLAY_MENU_DAC_CONFIGS(WAVEFORM_OUTPUT_DAC_MODE_SINE)
};
static WaveformOutputDACConfig dac_square_configs[] = {
    DISPLAY_MENU_DAC_CONFIGS(WAVEFORM_OUTPUT_DAC_MODE_SQUARE),
    {WAVEFORM_OUTPUT_DAC_MODE_SQUARE, 500000UL, 500U, 2800U}
};
static WaveformOutputDACConfig dac_triangle_configs[] = {
    DISPLAY_MENU_DAC_CONFIGS(WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE)
};
static WaveformOutputDACConfig dac_sawtooth_configs[] = {
    DISPLAY_MENU_DAC_CONFIGS(WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH)
};

#undef DISPLAY_MENU_DAC_CONFIGS

#define DISPLAY_MENU_DAC_ITEMS(configs) \
    {"1 HZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[0]},       \
    {"10 HZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[1]},      \
    {"100 HZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[2]},     \
    {"1 KHZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[3]},      \
    {"5 KHZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[4]},      \
    {"10 KHZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[5]},     \
    {"20 KHZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[6]},     \
    {"31.25 KHZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[7]},  \
    {"62.5 KHZ", NULL, DisplayMenuActionSetDACWaveform, &(configs)[8]}

static const MenuItem dac_sine_items[] = {
    DISPLAY_MENU_DAC_ITEMS(dac_sine_configs)
};

static const MenuPage dac_sine_page = {
    "DAC SINE",
    dac_sine_items,
    sizeof(dac_sine_items) / sizeof(dac_sine_items[0])
};

static const MenuItem dac_square_items[] = {
    DISPLAY_MENU_DAC_ITEMS(dac_square_configs),
    {"500 KHZ", NULL, DisplayMenuActionSetDACWaveform,
        &dac_square_configs[9]}
};

static const MenuPage dac_square_page = {
    "DAC SQUARE",
    dac_square_items,
    sizeof(dac_square_items) / sizeof(dac_square_items[0])
};

static const MenuItem dac_triangle_items[] = {
    DISPLAY_MENU_DAC_ITEMS(dac_triangle_configs)
};

static const MenuPage dac_triangle_page = {
    "DAC TRIANGLE",
    dac_triangle_items,
    sizeof(dac_triangle_items) / sizeof(dac_triangle_items[0])
};

static const MenuItem dac_sawtooth_items[] = {
    DISPLAY_MENU_DAC_ITEMS(dac_sawtooth_configs)
};

static const MenuPage dac_sawtooth_page = {
    "DAC SAWTOOTH",
    dac_sawtooth_items,
    sizeof(dac_sawtooth_items) / sizeof(dac_sawtooth_items[0])
};

#undef DISPLAY_MENU_DAC_ITEMS

static const MenuItem dac_output_items[] = {
    {"OUTPUT OFF", NULL, DisplayMenuActionStopDAC, NULL},
    {"DC LEVEL", &dac_dc_page, NULL, NULL},
    {"LOWER LIMIT", &dac_lower_limit_page, NULL, NULL},
    {"UPPER LIMIT", &dac_upper_limit_page, NULL, NULL},
    {"SINE", &dac_sine_page, NULL, NULL},
    {"SQUARE", &dac_square_page, NULL, NULL},
    {"TRIANGLE", &dac_triangle_page, NULL, NULL},
    {"SAWTOOTH", &dac_sawtooth_page, NULL, NULL}
};

static const MenuPage dac_output_page = {
    "DAC OUTPUT",
    dac_output_items,
    sizeof(dac_output_items) / sizeof(dac_output_items[0])
};
#endif

#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
/* 任意波形槽位菜单：选择槽位后先从 Flash 装载，再启动 PA15 DAC 循环输出。 */
static const uint8_t arbitrary_waveform_slot_ids[] = {0U, 1U, 2U};

static const MenuItem arbitrary_waveform_items[] = {
    {"SLOT 0 PLAY", NULL, DisplayMenuActionStartArbitraryWaveform,
        (void *)&arbitrary_waveform_slot_ids[0]},
    {"SLOT 1 PLAY", NULL, DisplayMenuActionStartArbitraryWaveform,
        (void *)&arbitrary_waveform_slot_ids[1]},
    {"SLOT 2 PLAY", NULL, DisplayMenuActionStartArbitraryWaveform,
        (void *)&arbitrary_waveform_slot_ids[2]},
    {"OUTPUT OFF", NULL, DisplayMenuActionStopArbitraryWaveform, NULL}
};

static const MenuPage arbitrary_waveform_page = {
    "ARBITRARY DAC",
    arbitrary_waveform_items,
    sizeof(arbitrary_waveform_items) /
        sizeof(arbitrary_waveform_items[0])
};
#endif

#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
/* PA27 阈值触发菜单：关闭、单次保存和信号回落后的连续轮换保存。 */
static const PA27ThresholdTriggerMode_e pa27_trigger_menu_modes[] = {
    PA27_THRESHOLD_TRIGGER_MODE_OFF,
    PA27_THRESHOLD_TRIGGER_MODE_SINGLE,
    PA27_THRESHOLD_TRIGGER_MODE_CONTINUOUS
};

static const MenuItem pa27_threshold_trigger_items[] = {
    {"OFF", NULL, DisplayMenuActionSetPA27TriggerMode,
        (void *)&pa27_trigger_menu_modes[0]},
    {"SINGLE", NULL, DisplayMenuActionSetPA27TriggerMode,
        (void *)&pa27_trigger_menu_modes[1]},
    {"CONTINUOUS", NULL, DisplayMenuActionSetPA27TriggerMode,
        (void *)&pa27_trigger_menu_modes[2]}
};

static const MenuPage pa27_threshold_trigger_page = {
    "PA27 TRIGGER",
    pa27_threshold_trigger_items,
    sizeof(pa27_threshold_trigger_items) /
        sizeof(pa27_threshold_trigger_items[0])
};
#endif

#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
/* PWM 菜单使用常用预设值，避免在双按键界面中逐位编辑数字。 */
static uint32_t pwm_frequency_levels_hz[] = {
    50U, 100U, 500U, 1000U, 5000U, 10000U, 20000U
};

static const MenuItem pwm_frequency_items[] = {
    {"50 HZ", NULL, DisplayMenuActionSetPWMFrequency,
        &pwm_frequency_levels_hz[0]},
    {"100 HZ", NULL, DisplayMenuActionSetPWMFrequency,
        &pwm_frequency_levels_hz[1]},
    {"500 HZ", NULL, DisplayMenuActionSetPWMFrequency,
        &pwm_frequency_levels_hz[2]},
    {"1 KHZ", NULL, DisplayMenuActionSetPWMFrequency,
        &pwm_frequency_levels_hz[3]},
    {"5 KHZ", NULL, DisplayMenuActionSetPWMFrequency,
        &pwm_frequency_levels_hz[4]},
    {"10 KHZ", NULL, DisplayMenuActionSetPWMFrequency,
        &pwm_frequency_levels_hz[5]},
    {"20 KHZ", NULL, DisplayMenuActionSetPWMFrequency,
        &pwm_frequency_levels_hz[6]}
};

static const MenuPage pwm_frequency_page = {
    "PWM FREQUENCY",
    pwm_frequency_items,
    sizeof(pwm_frequency_items) / sizeof(pwm_frequency_items[0])
};

static uint8_t pwm_duty_cycle_levels_percent[] = {
    0U, 10U, 25U, 50U, 75U, 90U, 100U
};

static const MenuItem pwm_duty_cycle_items[] = {
    {"0 PERCENT", NULL, DisplayMenuActionSetPWMDutyCycle,
        &pwm_duty_cycle_levels_percent[0]},
    {"10 PERCENT", NULL, DisplayMenuActionSetPWMDutyCycle,
        &pwm_duty_cycle_levels_percent[1]},
    {"25 PERCENT", NULL, DisplayMenuActionSetPWMDutyCycle,
        &pwm_duty_cycle_levels_percent[2]},
    {"50 PERCENT", NULL, DisplayMenuActionSetPWMDutyCycle,
        &pwm_duty_cycle_levels_percent[3]},
    {"75 PERCENT", NULL, DisplayMenuActionSetPWMDutyCycle,
        &pwm_duty_cycle_levels_percent[4]},
    {"90 PERCENT", NULL, DisplayMenuActionSetPWMDutyCycle,
        &pwm_duty_cycle_levels_percent[5]},
    {"100 PERCENT", NULL, DisplayMenuActionSetPWMDutyCycle,
        &pwm_duty_cycle_levels_percent[6]}
};

static const MenuPage pwm_duty_cycle_page = {
    "PWM DUTY CYCLE",
    pwm_duty_cycle_items,
    sizeof(pwm_duty_cycle_items) / sizeof(pwm_duty_cycle_items[0])
};

static const MenuItem pwm_output_items[] = {
    {"OUTPUT ON", NULL, DisplayMenuActionStartPWM, NULL},
    {"OUTPUT OFF", NULL, DisplayMenuActionStopPWM, NULL},
    {"FREQUENCY", &pwm_frequency_page, NULL, NULL},
    {"DUTY CYCLE", &pwm_duty_cycle_page, NULL, NULL}
};

static const MenuPage pwm_output_page = {
    "PWM OUTPUT",
    pwm_output_items,
    sizeof(pwm_output_items) / sizeof(pwm_output_items[0])
};
#endif

#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U)
/* DDS 菜单使用静态预设，适合双按键界面快速切换常用参数。 */
static WaveformOutputDDSWaveform_e dds_waveform_levels[] = {
    WAVEFORM_OUTPUT_DDS_WAVEFORM_SINE,
    WAVEFORM_OUTPUT_DDS_WAVEFORM_TRIANGLE,
    WAVEFORM_OUTPUT_DDS_WAVEFORM_SQUARE
};

static const MenuItem dds_waveform_items[] = {
    {"SINE", NULL, DisplayMenuActionSetDDSWaveform,
        &dds_waveform_levels[0]},
    {"TRIANGLE", NULL, DisplayMenuActionSetDDSWaveform,
        &dds_waveform_levels[1]},
    {"SQUARE", NULL, DisplayMenuActionSetDDSWaveform,
        &dds_waveform_levels[2]}
};

static const MenuPage dds_waveform_page = {
    "DDS WAVEFORM",
    dds_waveform_items,
    sizeof(dds_waveform_items) / sizeof(dds_waveform_items[0])
};

static uint32_t dds_frequency_levels_hz[] = {
    1U, 10U, 100U, 1000U, 10000U, 100000U, 1000000U
};

static const MenuItem dds_frequency_items[] = {
    {"1 HZ", NULL, DisplayMenuActionSetDDSFrequency,
        &dds_frequency_levels_hz[0]},
    {"10 HZ", NULL, DisplayMenuActionSetDDSFrequency,
        &dds_frequency_levels_hz[1]},
    {"100 HZ", NULL, DisplayMenuActionSetDDSFrequency,
        &dds_frequency_levels_hz[2]},
    {"1 KHZ", NULL, DisplayMenuActionSetDDSFrequency,
        &dds_frequency_levels_hz[3]},
    {"10 KHZ", NULL, DisplayMenuActionSetDDSFrequency,
        &dds_frequency_levels_hz[4]},
    {"100 KHZ", NULL, DisplayMenuActionSetDDSFrequency,
        &dds_frequency_levels_hz[5]},
    {"1 MHZ", NULL, DisplayMenuActionSetDDSFrequency,
        &dds_frequency_levels_hz[6]}
};

static const MenuPage dds_frequency_page = {
    "DDS FREQUENCY",
    dds_frequency_items,
    sizeof(dds_frequency_items) / sizeof(dds_frequency_items[0])
};

static uint16_t dds_phase_levels_degrees[] = {
    0U, 45U, 90U, 180U, 270U
};

static const MenuItem dds_phase_items[] = {
    {"0 DEG", NULL, DisplayMenuActionSetDDSPhase,
        &dds_phase_levels_degrees[0]},
    {"45 DEG", NULL, DisplayMenuActionSetDDSPhase,
        &dds_phase_levels_degrees[1]},
    {"90 DEG", NULL, DisplayMenuActionSetDDSPhase,
        &dds_phase_levels_degrees[2]},
    {"180 DEG", NULL, DisplayMenuActionSetDDSPhase,
        &dds_phase_levels_degrees[3]},
    {"270 DEG", NULL, DisplayMenuActionSetDDSPhase,
        &dds_phase_levels_degrees[4]}
};

static const MenuPage dds_phase_page = {
    "DDS PHASE",
    dds_phase_items,
    sizeof(dds_phase_items) / sizeof(dds_phase_items[0])
};

static const MenuItem dds_output_items[] = {
    {"OUTPUT ON", NULL, DisplayMenuActionStartDDS, NULL},
    {"OUTPUT OFF", NULL, DisplayMenuActionStopDDS, NULL},
    {"WAVEFORM", &dds_waveform_page, NULL, NULL},
    {"FREQUENCY", &dds_frequency_page, NULL, NULL},
    {"PHASE", &dds_phase_page, NULL, NULL}
};

static const MenuPage dds_output_page = {
    "DDS OUTPUT",
    dds_output_items,
    sizeof(dds_output_items) / sizeof(dds_output_items[0])
};
#endif

#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)
static WaveformOutputAD9850Waveform_e ad9850_waveform_levels[] = {
    WAVEFORM_OUTPUT_AD9850_WAVEFORM_SINE,
    WAVEFORM_OUTPUT_AD9850_WAVEFORM_SQUARE
};

static const MenuItem ad9850_waveform_items[] = {
    {"SIN PIN", NULL, DisplayMenuActionSetAD9850Waveform,
        &ad9850_waveform_levels[0]},
    {"SQ PIN", NULL, DisplayMenuActionSetAD9850Waveform,
        &ad9850_waveform_levels[1]}
};

static const MenuPage ad9850_waveform_page = {
    "AD9850 OUTPUT PIN",
    ad9850_waveform_items,
    sizeof(ad9850_waveform_items) / sizeof(ad9850_waveform_items[0])
};

static uint32_t ad9850_frequency_levels_hz[] = {
    1U, 10U, 100U, 1000U, 10000U, 100000U,
    1000000U, 10000000U, 20000000U, 40000000U
};

static const MenuItem ad9850_frequency_items[] = {
    {"1 HZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[0]},
    {"10 HZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[1]},
    {"100 HZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[2]},
    {"1 KHZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[3]},
    {"10 KHZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[4]},
    {"100 KHZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[5]},
    {"1 MHZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[6]},
    {"10 MHZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[7]},
    {"20 MHZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[8]},
    {"40 MHZ", NULL, DisplayMenuActionSetAD9850Frequency,
        &ad9850_frequency_levels_hz[9]}
};

static const MenuPage ad9850_frequency_page = {
    "AD9850 FREQUENCY",
    ad9850_frequency_items,
    sizeof(ad9850_frequency_items) / sizeof(ad9850_frequency_items[0])
};

static const MenuItem ad9850_output_items[] = {
    {"OUTPUT ON", NULL, DisplayMenuActionStartAD9850, NULL},
    {"OUTPUT OFF", NULL, DisplayMenuActionStopAD9850, NULL},
    {"OUTPUT PIN", &ad9850_waveform_page, NULL, NULL},
    {"FREQUENCY", &ad9850_frequency_page, NULL, NULL}
};

static const MenuPage ad9850_output_page = {
    "AD9850 OUTPUT",
    ad9850_output_items,
    sizeof(ad9850_output_items) / sizeof(ad9850_output_items[0])
};
#endif

#if APP_ENABLE_WAVEFORM_MAPPING != 0U
static const MenuItem waveform_mapping_items[] = {
    {"MEASURE PA27", NULL,
        DisplayMenuActionRequestWaveformMapping, NULL},
    {"OUTPUT OFF", NULL,
        DisplayMenuActionStopWaveformMapping, NULL}
};

static const MenuPage waveform_mapping_page = {
#if APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U
    "PA27 TO DAC",
#elif APP_WAVEFORM_MAPPING_BACKEND_AD9833 != 0U
    "PA27 TO AD9833",
#else
    "PA27 TO AD9850",
#endif
    waveform_mapping_items,
    sizeof(waveform_mapping_items) /
        sizeof(waveform_mapping_items[0])
};
#endif

static const MenuItem display_items[] = {
    {"NORMAL", NULL, DisplayMenuActionNormal, NULL},
    {"INVERT", NULL, DisplayMenuActionInvert, NULL},
    {"CONTRAST +", NULL, DisplayMenuActionContrastUp, NULL},
    {"CONTRAST -", NULL, DisplayMenuActionContrastDown, NULL}
};

static const MenuPage display_page = {
    "DISPLAY",
    display_items,
    sizeof(display_items) / sizeof(display_items[0])
};

static const MenuItem information_items[] = {
    {"MSPM0G3507", NULL, NULL, NULL},
#if APP_ENABLE_TFT_MENU != 0U
    {"ST7735S TFT", NULL, NULL, NULL},
    {"128X160", NULL, NULL, NULL},
    {"SPI0 8MHZ", NULL, NULL, NULL},
#else
    {"SSD1306 OLED", NULL, NULL, NULL},
    {"128X64", NULL, NULL, NULL},
    {"I2C 400KHZ", NULL, NULL, NULL},
#endif
    {"S1 NEXT/OK", NULL, NULL, NULL},
    {"S2 PREV/BACK", NULL, NULL, NULL}
};

static const MenuPage information_page = {
    "INFORMATION",
    information_items,
    sizeof(information_items) / sizeof(information_items[0])
};

#if APP_ENABLE_UART3 != 0U
#define DISPLAY_MENU_UART3_DIRECT(label_text, command_text) \
    {label_text, command_text "\r\n", NULL, NULL}
#define DISPLAY_MENU_UART3_PARAMETER(label_text, key_text, prompt_text, value_text) \
    {label_text, key_text "\r\n", prompt_text, value_text "\r\n"}

static const DisplayMenuUART3Command uart3_frequency_commands[] = {
    DISPLAY_MENU_UART3_PARAMETER("DDS A 100HZ", "key01", "FREQ(1~1M Hz)", "100"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A 1KHZ", "key01", "FREQ(1~1M Hz)", "1000"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A 10KHZ", "key01", "FREQ(1~1M Hz)", "10000"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A 100KHZ", "key01", "FREQ(1~1M Hz)", "100000"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A 1MHZ", "key01", "FREQ(1~1M Hz)", "1000000")
};

static const DisplayMenuUART3Command uart3_amplitude_commands[] = {
    DISPLAY_MENU_UART3_PARAMETER("DDS A AMP 0", "key02", "AMP(0~255)", "0"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A AMP 64", "key02", "AMP(0~255)", "64"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A AMP 128", "key02", "AMP(0~255)", "128"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A AMP 192", "key02", "AMP(0~255)", "192"),
    DISPLAY_MENU_UART3_PARAMETER("DDS A AMP 255", "key02", "AMP(0~255)", "255")
};

static const DisplayMenuUART3Command uart3_phase_value_commands[] = {
    DISPLAY_MENU_UART3_DIRECT("PHASE 0", "phase0"),
    DISPLAY_MENU_UART3_DIRECT("PHASE 45", "phase45"),
    DISPLAY_MENU_UART3_DIRECT("PHASE 90", "phase90"),
    DISPLAY_MENU_UART3_DIRECT("PHASE 180", "phase180"),
    DISPLAY_MENU_UART3_DIRECT("PHASE 270", "phase270"),
    DISPLAY_MENU_UART3_DIRECT("PHI 90", "phi90")
};

static const DisplayMenuUART3Command uart3_capture_commands[] = {
    DISPLAY_MENU_UART3_DIRECT("SEP1 A MODEL", "sep1"),
    DISPLAY_MENU_UART3_DIRECT("SEP2 AB MODEL", "sep2"),
    DISPLAY_MENU_UART3_DIRECT("FILTER ON", "filter"),
    DISPLAY_MENU_UART3_DIRECT("NORMAL", "normal"),
    DISPLAY_MENU_UART3_DIRECT("FILTER OFF", "filteroff"),
    DISPLAY_MENU_UART3_DIRECT("PLL PHASE", "phase"),
    DISPLAY_MENU_UART3_DIRECT("DDS PHASE PLL", "ddsphase")
};

static const DisplayMenuUART3Command uart3_measure_commands[] = {
    DISPLAY_MENU_UART3_DIRECT("MEASURE A", "measurea"),
    DISPLAY_MENU_UART3_DIRECT("MEASURE B", "measureb"),
    DISPLAY_MENU_UART3_DIRECT("COMPONENT A", "compa"),
    DISPLAY_MENU_UART3_DIRECT("COMPONENT B", "compb"),
    DISPLAY_MENU_UART3_DIRECT("FILTER DATA", "data"),
    DISPLAY_MENU_UART3_DIRECT("ADC DIAG", "adcdiag")
};

static const DisplayMenuUART3Command uart3_output_commands[] = {
    DISPLAY_MENU_UART3_DIRECT("OUTPUT A", "outputa"),
    DISPLAY_MENU_UART3_DIRECT("OUTPUT B", "outputb"),
    DISPLAY_MENU_UART3_DIRECT("OUTPUT AB", "output"),
    DISPLAY_MENU_UART3_DIRECT("SEP OUT A", "sepouta"),
    DISPLAY_MENU_UART3_DIRECT("SEP OUT B", "sepoutb"),
    DISPLAY_MENU_UART3_DIRECT("OUTPUT OFF", "outputoff")
};

static const DisplayMenuUART3Command uart3_sweep_commands[] = {
    DISPLAY_MENU_UART3_DIRECT("SWEEP", "sweep"),
    DISPLAY_MENU_UART3_DIRECT("SWEEP 1", "sweep1"),
    DISPLAY_MENU_UART3_DIRECT("SWEEP 2 AVG", "sweep2"),
    DISPLAY_MENU_UART3_DIRECT("INFERENCE", "infer")
};

#define DISPLAY_MENU_UART3_ITEM(commands, index) \
    {(commands)[index].label, NULL, DisplayMenuActionStartUART3Command, \
     (void *)&(commands)[index]}

static const MenuItem uart3_frequency_items[] = {
    DISPLAY_MENU_UART3_ITEM(uart3_frequency_commands, 0),
    DISPLAY_MENU_UART3_ITEM(uart3_frequency_commands, 1),
    DISPLAY_MENU_UART3_ITEM(uart3_frequency_commands, 2),
    DISPLAY_MENU_UART3_ITEM(uart3_frequency_commands, 3),
    DISPLAY_MENU_UART3_ITEM(uart3_frequency_commands, 4)
};
static const MenuPage uart3_frequency_page = {
    "UART3 DDS FREQ", uart3_frequency_items,
    sizeof(uart3_frequency_items) / sizeof(uart3_frequency_items[0])
};

static const MenuItem uart3_amplitude_items[] = {
    DISPLAY_MENU_UART3_ITEM(uart3_amplitude_commands, 0),
    DISPLAY_MENU_UART3_ITEM(uart3_amplitude_commands, 1),
    DISPLAY_MENU_UART3_ITEM(uart3_amplitude_commands, 2),
    DISPLAY_MENU_UART3_ITEM(uart3_amplitude_commands, 3),
    DISPLAY_MENU_UART3_ITEM(uart3_amplitude_commands, 4)
};
static const MenuPage uart3_amplitude_page = {
    "UART3 DDS AMP", uart3_amplitude_items,
    sizeof(uart3_amplitude_items) / sizeof(uart3_amplitude_items[0])
};

static const MenuItem uart3_phase_value_items[] = {
    DISPLAY_MENU_UART3_ITEM(uart3_phase_value_commands, 0),
    DISPLAY_MENU_UART3_ITEM(uart3_phase_value_commands, 1),
    DISPLAY_MENU_UART3_ITEM(uart3_phase_value_commands, 2),
    DISPLAY_MENU_UART3_ITEM(uart3_phase_value_commands, 3),
    DISPLAY_MENU_UART3_ITEM(uart3_phase_value_commands, 4),
    DISPLAY_MENU_UART3_ITEM(uart3_phase_value_commands, 5)
};
static const MenuPage uart3_phase_value_page = {
    "UART3 PHASE SET", uart3_phase_value_items,
    sizeof(uart3_phase_value_items) / sizeof(uart3_phase_value_items[0])
};

static const MenuItem uart3_capture_items[] = {
    DISPLAY_MENU_UART3_ITEM(uart3_capture_commands, 0),
    DISPLAY_MENU_UART3_ITEM(uart3_capture_commands, 1),
    DISPLAY_MENU_UART3_ITEM(uart3_capture_commands, 2),
    DISPLAY_MENU_UART3_ITEM(uart3_capture_commands, 3),
    DISPLAY_MENU_UART3_ITEM(uart3_capture_commands, 4),
    DISPLAY_MENU_UART3_ITEM(uart3_capture_commands, 5),
    DISPLAY_MENU_UART3_ITEM(uart3_capture_commands, 6)
};
static const MenuPage uart3_capture_page = {
    "UART3 MODE", uart3_capture_items,
    sizeof(uart3_capture_items) / sizeof(uart3_capture_items[0])
};

static const MenuItem uart3_measure_items[] = {
    DISPLAY_MENU_UART3_ITEM(uart3_measure_commands, 0),
    DISPLAY_MENU_UART3_ITEM(uart3_measure_commands, 1),
    DISPLAY_MENU_UART3_ITEM(uart3_measure_commands, 2),
    DISPLAY_MENU_UART3_ITEM(uart3_measure_commands, 3),
    DISPLAY_MENU_UART3_ITEM(uart3_measure_commands, 4),
    DISPLAY_MENU_UART3_ITEM(uart3_measure_commands, 5)
};
static const MenuPage uart3_measure_page = {
    "UART3 READBACK", uart3_measure_items,
    sizeof(uart3_measure_items) / sizeof(uart3_measure_items[0])
};

static const MenuItem uart3_output_items[] = {
    DISPLAY_MENU_UART3_ITEM(uart3_output_commands, 0),
    DISPLAY_MENU_UART3_ITEM(uart3_output_commands, 1),
    DISPLAY_MENU_UART3_ITEM(uart3_output_commands, 2),
    DISPLAY_MENU_UART3_ITEM(uart3_output_commands, 3),
    DISPLAY_MENU_UART3_ITEM(uart3_output_commands, 4),
    DISPLAY_MENU_UART3_ITEM(uart3_output_commands, 5)
};
static const MenuPage uart3_output_page = {
    "UART3 OUTPUT", uart3_output_items,
    sizeof(uart3_output_items) / sizeof(uart3_output_items[0])
};

static const MenuItem uart3_sweep_items[] = {
    DISPLAY_MENU_UART3_ITEM(uart3_sweep_commands, 0),
    DISPLAY_MENU_UART3_ITEM(uart3_sweep_commands, 1),
    DISPLAY_MENU_UART3_ITEM(uart3_sweep_commands, 2),
    DISPLAY_MENU_UART3_ITEM(uart3_sweep_commands, 3)
};
static const MenuPage uart3_sweep_page = {
    "UART3 SWEEP", uart3_sweep_items,
    sizeof(uart3_sweep_items) / sizeof(uart3_sweep_items[0])
};

static const MenuItem uart3_remote_items[] = {
    {"DDS A FREQUENCY", &uart3_frequency_page, NULL, NULL},
    {"DDS A AMPLITUDE", &uart3_amplitude_page, NULL, NULL},
    {"DDS B PHASE", &uart3_phase_value_page, NULL, NULL},
    {"CAPTURE / MODE", &uart3_capture_page, NULL, NULL},
    {"MEASURE / DIAG", &uart3_measure_page, NULL, NULL},
    {"MODEL OUTPUT", &uart3_output_page, NULL, NULL},
    {"SWEEP / INFER", &uart3_sweep_page, NULL, NULL}
};
static const MenuPage uart3_remote_page = {
    "UART3 REMOTE", uart3_remote_items,
    sizeof(uart3_remote_items) / sizeof(uart3_remote_items[0])
};

#undef DISPLAY_MENU_UART3_ITEM
#undef DISPLAY_MENU_UART3_PARAMETER
#undef DISPLAY_MENU_UART3_DIRECT
#endif

static const MenuItem root_items[] = {
    {"CUSTOM PAGE", NULL, DisplayMenuActionStartCustomPage, NULL},
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    {"WAVEFORM", &waveform_page, NULL, NULL},
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    {"FFT SPECTRUM", &fft_spectrum_page, NULL, NULL},
#endif
#if APP_ENABLE_UART3 != 0U
    {"UART3 REMOTE", &uart3_remote_page, NULL, NULL},
#endif
#if APP_ENABLE_WAVEFORM_MAPPING != 0U
    {"PA27 MAPPING", &waveform_mapping_page, NULL, NULL},
#endif
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U)
    {"DAC OUTPUT", &dac_output_page, NULL, NULL},
#endif
#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
    {"ARBITRARY DAC", &arbitrary_waveform_page, NULL, NULL},
#endif
#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
    {"PA27 TRIGGER", &pa27_threshold_trigger_page, NULL, NULL},
#endif
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
    {"PWM OUTPUT", &pwm_output_page, NULL, NULL},
#endif
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U)
    {"DDS OUTPUT", &dds_output_page, NULL, NULL},
#endif
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)
    {"AD9850 OUTPUT", &ad9850_output_page, NULL, NULL},
#endif
    {"DISPLAY", &display_page, NULL, NULL},
    {"INFORMATION", &information_page, NULL, NULL},
    {"RESET VIEW", NULL, DisplayMenuActionResetDisplay, NULL}
};

static const MenuPage root_page = {
    "MAIN MENU",
    root_items,
    sizeof(root_items) / sizeof(root_items[0])
};

/* 绑定已初始化的显示后端，并创建 10 ms 按键轮询任务。 */
bool DisplayMenuInit(DisplayInstance *display)
{
    static const uint8_t init_message[] = "DISPLAY MENU INIT\r\n";
    static const uint8_t error_message[] = "DISPLAY MENU ERROR\r\n";
    static const uint8_t ready_message[] = "DISPLAY MENU READY\r\n";
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    static const WaveformConfig waveform_config = {
        0U,
        12U,
        DISPLAY_WIDTH,
        DISPLAY_HEIGHT - 12U,
        -1000,
        1000,
        true
    };
#endif
    bool initial_page_ready;

    if (display_menu_task_created) {
        return menu_display == display;
    }

    DisplayMenuDebugSend(init_message, sizeof(init_message) - 1U);

    if (display == NULL) {
        DisplayMenuDebugSend(error_message, sizeof(error_message) - 1U);
        return false;
    }

    menu_display = display;
    next_button = ButtonRegister(BUTTON_DEVICE_NEXT);
    previous_button = ButtonRegister(BUTTON_DEVICE_PREVIOUS);
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    waveform = WaveformRegister(menu_display, &waveform_config);
#endif

    if ((menu_display == NULL) || (next_button == NULL) ||
        (previous_button == NULL)
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
        || (waveform == NULL)
#endif
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
        || !PWMOutputInit()
#endif
        || !CustomPageInit(menu_display)
        ) {
        DisplayMenuDebugSend(error_message, sizeof(error_message) - 1U);
        return false;
    }

#if APP_ENABLE_UART2 != 0U
    if (!SerialCommunicationUART2SubscribeSample(
            DisplayMenuUART2SampleReceived, NULL)) {
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
        (void)PWMOutputStop();
#endif
        (void)DisplaySetEnabled(menu_display, false);
        DisplayMenuDebugSend(error_message, sizeof(error_message) - 1U);
        return false;
    }
#endif
#if APP_ENABLE_UART3 != 0U
    if (!SerialCommunicationUART3SubscribeSample(
            DisplayMenuUART3SampleReceived, NULL)) {
#if APP_ENABLE_UART2 != 0U
        (void)SerialCommunicationUART2UnsubscribeSample(
            DisplayMenuUART2SampleReceived, NULL);
#endif
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
        (void)PWMOutputStop();
#endif
        (void)DisplaySetEnabled(menu_display, false);
        DisplayMenuDebugSend(error_message, sizeof(error_message) - 1U);
        return false;
    }
    if (!SerialCommunicationUART3SubscribeLine(
            DisplayMenuUART3LineReceived, NULL)) {
        (void)SerialCommunicationUART3UnsubscribeSample(
            DisplayMenuUART3SampleReceived, NULL);
#if APP_ENABLE_UART2 != 0U
        (void)SerialCommunicationUART2UnsubscribeSample(
            DisplayMenuUART2SampleReceived, NULL);
#endif
        (void)DisplaySetEnabled(menu_display, false);
        DisplayMenuDebugSend(error_message, sizeof(error_message) - 1U);
        return false;
    }
#endif

    menu = MenuRegister(menu_display, &root_page);
    custom_page_active =
        APP_DISPLAY_MENU_START_PAGE_CUSTOM != 0U;
    initial_page_ready = (menu != NULL) &&
        (custom_page_active ? CustomPageEnter() : MenuRender(menu));
    if ((menu == NULL) || !initial_page_ready ||
        (ApplicationTaskCreate(APPLICATION_TASK_DISPLAY_MENU,
             DisplayMenuTask, NULL) == NULL)) {
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
        (void)PWMOutputStop();
#endif
        if (menu_display != NULL) {
            (void)DisplaySetEnabled(menu_display, false);
        }
#if APP_ENABLE_UART2 != 0U
        (void)SerialCommunicationUART2UnsubscribeSample(
            DisplayMenuUART2SampleReceived, NULL);
#endif
#if APP_ENABLE_UART3 != 0U
        (void)SerialCommunicationUART3UnsubscribeSample(
            DisplayMenuUART3SampleReceived, NULL);
        (void)SerialCommunicationUART3UnsubscribeLine(
            DisplayMenuUART3LineReceived, NULL);
#endif
        DisplayMenuDebugSend(error_message, sizeof(error_message) - 1U);
        return false;
    }

    display_menu_task_created = true;
    DisplayMenuDebugSend(ready_message, sizeof(ready_message) - 1U);
    return true;
}

/*
 * 自定义页统一导航入口。菜单页通过 Menu 路径打开，整帧波形和
 * FFT 页则复用原有安全启动动作，不在自定义页里直接操作硬件。
 */
bool DisplayMenuOpenFromCustom(DisplayMenuRoute_e route)
{
    const MenuPage *target_page = NULL;
    Menu_Action_t target_action = NULL;
    bool target_started = false;

    if (!display_menu_task_created || !custom_page_active ||
        (route < DISPLAY_MENU_ROUTE_MAIN_MENU) ||
        (route >= DISPLAY_MENU_ROUTE_COUNT)) {
        return false;
    }

    switch (route) {
        case DISPLAY_MENU_ROUTE_MAIN_MENU:
            target_page = &root_page;
            break;

        case DISPLAY_MENU_ROUTE_WAVEFORM_MENU:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
            target_page = &waveform_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_WAVEFORM_PA27:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 != 0U)
            target_action = DisplayMenuActionStartADC27Waveform;
#endif
            break;

        case DISPLAY_MENU_ROUTE_WAVEFORM_PA21:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
            target_action = DisplayMenuActionStartADC21Waveform;
#endif
            break;

        case DISPLAY_MENU_ROUTE_WAVEFORM_UART2:
#if APP_ENABLE_UART2 != 0U
            target_action = DisplayMenuActionStartUART2Waveform;
#endif
            break;

        case DISPLAY_MENU_ROUTE_WAVEFORM_UART3:
#if APP_ENABLE_UART3 != 0U
            target_action = DisplayMenuActionStartUART3Waveform;
#endif
            break;

        case DISPLAY_MENU_ROUTE_FFT_MENU:
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
            target_page = &fft_spectrum_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_FFT_PA27:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 != 0U)
            target_action = DisplayMenuActionStartFFT27;
#endif
            break;

        case DISPLAY_MENU_ROUTE_FFT_PA21:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
            target_action = DisplayMenuActionStartFFT21;
#endif
            break;

        case DISPLAY_MENU_ROUTE_FFT_UART2:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_UART2 != 0U)
            target_action = DisplayMenuActionStartFFTUART2;
#endif
            break;

        case DISPLAY_MENU_ROUTE_FFT_UART3:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_UART3_SPECTRUM != 0U)
            target_action = DisplayMenuActionStartFFTUART3;
#endif
            break;

        case DISPLAY_MENU_ROUTE_PHASE_PAIR:
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
            target_action = DisplayMenuActionStartSynchronizedPhase;
#endif
            break;

        case DISPLAY_MENU_ROUTE_MAPPING_MENU:
#if APP_ENABLE_WAVEFORM_MAPPING != 0U
            target_page = &waveform_mapping_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_DAC_OUTPUT_MENU:
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U)
            target_page = &dac_output_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_ARBITRARY_WAVEFORM_MENU:
#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
            target_page = &arbitrary_waveform_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_PWM_OUTPUT_MENU:
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
            target_page = &pwm_output_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_DDS_OUTPUT_MENU:
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U)
            target_page = &dds_output_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_AD9850_OUTPUT_MENU:
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)
            target_page = &ad9850_output_page;
#endif
            break;

        case DISPLAY_MENU_ROUTE_DISPLAY_SETTINGS_MENU:
            target_page = &display_page;
            break;

        case DISPLAY_MENU_ROUTE_INFORMATION_MENU:
            target_page = &information_page;
            break;

        case DISPLAY_MENU_ROUTE_COUNT:
        default:
            return false;
    }

    if (target_page != NULL) {
        return DisplayMenuOpenMenuPageFromCustom(target_page);
    }
    if (target_action == NULL) {
        /* 目标被 app_config.h 关闭，保持自定义页不变。 */
        return false;
    }

    display_menu_return_target = DISPLAY_MENU_RETURN_CUSTOM_PAGE;
    display_menu_return_depth  = 0U;
    custom_page_active         = false;
    target_action(NULL);

    if (action_feedback_active) {
        (void)DisplayMenuRenderActionFeedback();
    }

    if ((route == DISPLAY_MENU_ROUTE_WAVEFORM_PA27) ||
        (route == DISPLAY_MENU_ROUTE_WAVEFORM_PA21) ||
        (route == DISPLAY_MENU_ROUTE_WAVEFORM_UART2) ||
        (route == DISPLAY_MENU_ROUTE_WAVEFORM_UART3)) {
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
        target_started = waveform_active;
#endif
    } else if (route == DISPLAY_MENU_ROUTE_PHASE_PAIR) {
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
        target_started = phase_active;
#endif
    } else {
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
        target_started = spectrum_active;
#endif
    }

    if (!target_started) {
        /* 例如 ADC 已有请求在执行：提示结束后仍回到自定义页。 */
        display_menu_return_target = DISPLAY_MENU_RETURN_MAIN_MENU;
        custom_page_active = true;
    }
    return true;
}

/* 打开普通菜单页并保存入口深度，回退到该层时再返回自定义页。 */
static bool DisplayMenuOpenMenuPageFromCustom(
    const MenuPage *target_page)
{
    if ((menu == NULL) || (target_page == NULL) ||
        !MenuNavigateToPage(menu, target_page)) {
        return false;
    }

    display_menu_return_target = DISPLAY_MENU_RETURN_CUSTOM_PAGE;
    display_menu_return_depth  = MenuGetDepth(menu);
    custom_page_active         = false;
    if (MenuRender(menu)) {
        return true;
    }

    display_menu_return_target = DISPLAY_MENU_RETURN_MAIN_MENU;
    display_menu_return_depth  = 0U;
    custom_page_active         = true;
    (void)CustomPageResume();
    return false;
}

/* 波形、FFT 和菜单边界共用的返回出口。 */
static void DisplayMenuReturnFromCurrentPage(void)
{
    bool return_to_custom =
        display_menu_return_target == DISPLAY_MENU_RETURN_CUSTOM_PAGE;

    display_menu_return_target = DISPLAY_MENU_RETURN_MAIN_MENU;
    display_menu_return_depth  = 0U;

    if (return_to_custom) {
        custom_page_active = true;
        if (CustomPageResume()) {
            return;
        }
        custom_page_active = false;
    }
    (void)MenuRender(menu);
}

/* ADC 页已改为测量完成后读取整个快照，不再接收逐点实时数据。 */
bool DisplayMenuSubmitADCWaveformSample(int16_t sample)
{
    (void)sample;
    return false;
}

/* 仅在 UART2 外部波形页面运行时接收串口采样。 */
bool DisplayMenuSubmitUART2WaveformSample(int16_t sample)
{
#if APP_ENABLE_UART2 != 0U
    return DisplayMenuSubmitWaveformSampleForSource(
        DISPLAY_MENU_WAVEFORM_SOURCE_UART2, sample);
#else
    (void)sample;
    return false;
#endif
}

/* 仅在 UART3 外部波形页面运行时接收串口采样。 */
bool DisplayMenuSubmitUART3WaveformSample(int16_t sample)
{
#if APP_ENABLE_UART3 != 0U
    return DisplayMenuSubmitWaveformSampleForSource(
        DISPLAY_MENU_WAVEFORM_SOURCE_UART3, sample);
#else
    (void)sample;
    return false;
#endif
}

uint32_t DisplayMenuGetMinimumFreeStackWords(void)
{
    return display_menu_minimum_free_stack_words;
}

#if APP_ENABLE_UART2 != 0U
static void DisplayMenuUART2SampleReceived(
    int16_t sample, void *context)
{
    (void)context;
    (void)DisplayMenuSubmitUART2WaveformSample(sample);
}
#endif

#if APP_ENABLE_UART3 != 0U
static void DisplayMenuUART3SampleReceived(
    int16_t sample, void *context)
{
    (void)context;
    (void)DisplayMenuSubmitUART3WaveformSample(sample);
}

/* 对非 NUL 结尾的接收行执行有界子串查找。 */
static bool DisplayMenuUART3TextContains(
    const uint8_t *data, size_t size, const char *fragment)
{
    size_t fragment_size = strlen(fragment);
    size_t index;

    if ((fragment_size == 0U) || (fragment_size > size)) {
        return false;
    }
    for (index = 0U; index <= size - fragment_size; ++index) {
        if (memcmp(&data[index], fragment, fragment_size) == 0) {
            return true;
        }
    }
    return false;
}

/* 文本命令页消费所有 UART3 行，并把长行切成 LCD 可显示的 20 字符片段。 */
static bool DisplayMenuUART3LineReceived(
    const uint8_t *data, size_t size, void *context)
{
    size_t offset = 0U;
    bool is_prompt;
    bool is_error;

    (void)context;
    if (!uart3_text_active || (data == NULL) || (size == 0U)) {
        return false;
    }

    is_prompt = (uart3_text_command != NULL) &&
        (uart3_text_command->prompt != NULL) &&
        (size == strlen(uart3_text_command->prompt)) &&
        (memcmp(data, uart3_text_command->prompt, size) == 0);
    is_error = DisplayMenuUART3TextContains(data, size, "error") ||
        DisplayMenuUART3TextContains(data, size, "ERROR") ||
        DisplayMenuUART3TextContains(data, size, "INVALID") ||
        DisplayMenuUART3TextContains(data, size, "NOT READY") ||
        DisplayMenuUART3TextContains(data, size, "NOT AVAILABLE") ||
        DisplayMenuUART3TextContains(data, size, "OUT OF RANGE") ||
        DisplayMenuUART3TextContains(data, size, "REQUIRES") ||
        DisplayMenuUART3TextContains(data, size, "FAILED") ||
        DisplayMenuUART3TextContains(data, size, "TIMEOUT") ||
        DisplayMenuUART3TextContains(data, size, "Unknown");

    taskENTER_CRITICAL();
    while (offset < size) {
        size_t chunk_size = size - offset;
        char *destination;

        if (chunk_size > DISPLAY_MENU_UART3_TEXT_LINE_LENGTH) {
            chunk_size = DISPLAY_MENU_UART3_TEXT_LINE_LENGTH;
        }
        if (uart3_text_line_count >= DISPLAY_MENU_UART3_TEXT_LINE_COUNT) {
            memmove(&uart3_text_lines[0], &uart3_text_lines[1],
                (DISPLAY_MENU_UART3_TEXT_LINE_COUNT - 1U) *
                sizeof(uart3_text_lines[0]));
            uart3_text_line_count = DISPLAY_MENU_UART3_TEXT_LINE_COUNT - 1U;
        }
        destination = uart3_text_lines[uart3_text_line_count];
        memcpy(destination, &data[offset], chunk_size);
        destination[chunk_size] = '\0';
        ++uart3_text_line_count;
        offset += chunk_size;
    }
    uart3_text_page = (uint8_t)((uart3_text_line_count - 1U) /
        DISPLAY_MENU_UART3_TEXT_VISIBLE_LINES);
    if (is_error) {
        uart3_text_status = DISPLAY_MENU_UART3_TEXT_ERROR;
    } else if (is_prompt && !uart3_text_argument_sent) {
        uart3_text_argument_pending = true;
        uart3_text_status = DISPLAY_MENU_UART3_TEXT_WAIT;
        uart3_text_deadline = xTaskGetTickCount() +
            pdMS_TO_TICKS(DISPLAY_MENU_UART3_TEXT_TIMEOUT_MS);
    } else {
        uart3_text_status = DISPLAY_MENU_UART3_TEXT_RX;
    }
    uart3_text_dirty = true;
    taskEXIT_CRITICAL();
    return true;
}

/* 发送调用方提供的完整协议文本，不在此处自动追加 CRLF。 */
static bool DisplayMenuSendUART3CommandText(const char *text)
{
    return (text != NULL) &&
        SerialCommunicationUART3Send(
            (const uint8_t *)text, strlen(text));
}

/* 先建立行接收状态再发送，避免快速返回的首行落入旧解析路径。 */
static bool DisplayMenuStartUART3Command(
    const DisplayMenuUART3Command *command)
{
    bool sent;

    if ((command == NULL) || (command->command == NULL)) {
        return false;
    }
    SerialCommunicationUART3CancelRequest();
    taskENTER_CRITICAL();
    memset(uart3_text_lines, 0, sizeof(uart3_text_lines));
    uart3_text_command = command;
    uart3_text_line_count = 0U;
    uart3_text_page = 0U;
    uart3_text_argument_pending = false;
    uart3_text_argument_sent = false;
    uart3_text_status = DISPLAY_MENU_UART3_TEXT_WAIT;
    uart3_text_deadline = xTaskGetTickCount() +
        pdMS_TO_TICKS(DISPLAY_MENU_UART3_TEXT_TIMEOUT_MS);
    uart3_text_dirty = true;
    uart3_text_active = true;
    taskEXIT_CRITICAL();

    sent = DisplayMenuSendUART3CommandText(command->command);
    if (!sent) {
        taskENTER_CRITICAL();
        uart3_text_status = DISPLAY_MENU_UART3_TEXT_ERROR;
        uart3_text_dirty = true;
        taskEXIT_CRITICAL();
    }
    return sent;
}

static void DisplayMenuActionStartUART3Command(void *context)
{
    (void)DisplayMenuStartUART3Command(
        (const DisplayMenuUART3Command *)context);
    (void)DisplayMenuRenderUART3TextPage();
}

/* 从共享行缓冲快照当前页，每页最多绘制五个 20 字符片段。 */
static bool DisplayMenuRenderUART3TextPage(void)
{
    char title[16];
    char line[DISPLAY_MENU_UART3_TEXT_LINE_LENGTH + 1U];
    const char *status_label;
    uint8_t line_count;
    uint8_t page;
    uint8_t first_line;
    uint8_t visible_index;
    size_t title_size;

    switch (uart3_text_status) {
        case DISPLAY_MENU_UART3_TEXT_WAIT: status_label = "WAIT"; break;
        case DISPLAY_MENU_UART3_TEXT_RX: status_label = "RX"; break;
        case DISPLAY_MENU_UART3_TEXT_ERROR: status_label = "ERR"; break;
        case DISPLAY_MENU_UART3_TEXT_TIMEOUT: status_label = "TIME"; break;
        default: status_label = "IDLE"; break;
    }
    title_size = (uart3_text_command != NULL)
        ? strlen(uart3_text_command->label) : 0U;
    if (title_size > sizeof(title) - 1U) {
        title_size = sizeof(title) - 1U;
    }
    if (title_size > 0U) {
        memcpy(title, uart3_text_command->label, title_size);
    }
    title[title_size] = '\0';

    taskENTER_CRITICAL();
    line_count = uart3_text_line_count;
    page = uart3_text_page;
    taskEXIT_CRITICAL();
    first_line = (uint8_t)(page * DISPLAY_MENU_UART3_TEXT_VISIBLE_LINES);

    if (!DisplayClear(menu_display, false) ||
        !DisplayDrawString(menu_display, 0U, 0U, title) ||
        !DisplayDrawString(menu_display, 102U, 0U, status_label)) {
        return false;
    }
    for (visible_index = 0U;
         visible_index < DISPLAY_MENU_UART3_TEXT_VISIBLE_LINES;
         ++visible_index) {
        uint8_t source_index = (uint8_t)(first_line + visible_index);

        if (source_index >= line_count) {
            break;
        }
        taskENTER_CRITICAL();
        memcpy(line, uart3_text_lines[source_index], sizeof(line));
        taskEXIT_CRITICAL();
        if (!DisplayDrawString(menu_display, 0U,
                (uint8_t)(12U + visible_index * 10U), line)) {
            return false;
        }
    }
    return DisplayUpdate(menu_display);
}

/* 处理二阶段参数发送、超时、翻页、重发和退出，所有刷屏都留在菜单任务。 */
static void DisplayMenuProcessUART3TextPage(
    Button_Event_e next_event, Button_Event_e previous_event)
{
    bool argument_pending;
    bool dirty;

    taskENTER_CRITICAL();
    argument_pending = uart3_text_argument_pending;
    uart3_text_argument_pending = false;
    taskEXIT_CRITICAL();
    if (argument_pending && (uart3_text_command != NULL) &&
        (uart3_text_command->argument != NULL)) {
        bool sent = DisplayMenuSendUART3CommandText(
            uart3_text_command->argument);

        taskENTER_CRITICAL();
        uart3_text_argument_sent = sent;
        if (!sent) {
            uart3_text_status = DISPLAY_MENU_UART3_TEXT_ERROR;
        }
        uart3_text_dirty = true;
        taskEXIT_CRITICAL();
    }

    if ((uart3_text_status == DISPLAY_MENU_UART3_TEXT_WAIT) &&
        ((int32_t)(xTaskGetTickCount() - uart3_text_deadline) >= 0)) {
        taskENTER_CRITICAL();
        uart3_text_status = DISPLAY_MENU_UART3_TEXT_TIMEOUT;
        uart3_text_dirty = true;
        taskEXIT_CRITICAL();
    }
    if (next_event == BUTTON_EVENT_SHORT_PRESS) {
        uint8_t page_count = (uint8_t)((uart3_text_line_count +
            DISPLAY_MENU_UART3_TEXT_VISIBLE_LINES - 1U) /
            DISPLAY_MENU_UART3_TEXT_VISIBLE_LINES);

        if (page_count > 1U) {
            uart3_text_page = (uint8_t)((uart3_text_page + 1U) % page_count);
            uart3_text_dirty = true;
        }
    } else if (next_event == BUTTON_EVENT_LONG_PRESS) {
        (void)DisplayMenuStartUART3Command(uart3_text_command);
    }
    if (previous_event == BUTTON_EVENT_LONG_PRESS) {
        taskENTER_CRITICAL();
        uart3_text_active = false;
        uart3_text_argument_pending = false;
        taskEXIT_CRITICAL();
        DisplayMenuReturnFromCurrentPage();
        return;
    }

    taskENTER_CRITICAL();
    dirty = uart3_text_dirty;
    uart3_text_dirty = false;
    taskEXIT_CRITICAL();
    if (dirty) {
        (void)DisplayMenuRenderUART3TextPage();
    }
}
#endif

/* 周期处理两个按键事件，并只在菜单状态变化时刷新当前显示屏。 */
static void DisplayMenuTask(void *argument)
{
    /* 使用绝对唤醒时间维持稳定的 10 ms 按键扫描周期。 */
    TickType_t next_wake_time = xTaskGetTickCount();
    TickType_t previous_button_tick = next_wake_time;

    (void)argument;

    /* 每轮先读取按键，再根据当前页面状态处理菜单、波形或频谱业务。 */
    for (;;) {
        TickType_t current_button_tick = xTaskGetTickCount();
        TickType_t button_elapsed_ticks =
            current_button_tick - previous_button_tick;
        uint32_t button_elapsed_ms =
            (uint32_t)pdTICKS_TO_MS(button_elapsed_ticks);

        previous_button_tick = current_button_tick;
        if (button_elapsed_ms == 0U) {
            /* 兼容 Tick 分辨率低于当前调用间隔的配置。 */
            button_elapsed_ms = 1U;
        }

        /*
         * 每秒读取一次 0xA5 栈填充值。该值记录任务启动以来的历史最小
         * 空闲栈，可在调试器中观察 DisplayMenuGetMinimumFreeStackWords()。
         */
        if ((button_elapsed_ms >=
                DISPLAY_MENU_STACK_DIAGNOSTIC_PERIOD_MS) ||
            (display_menu_stack_diagnostic_elapsed_ms >=
                DISPLAY_MENU_STACK_DIAGNOSTIC_PERIOD_MS -
                    button_elapsed_ms)) {
            display_menu_stack_diagnostic_elapsed_ms = 0U;
            display_menu_minimum_free_stack_words =
                ApplicationTaskGetMinimumFreeStackWords(
                    APPLICATION_TASK_DISPLAY_MENU);
        } else {
            display_menu_stack_diagnostic_elapsed_ms += button_elapsed_ms;
        }

        /*
         * 每轮只读取一次按键。使用实际 Tick 间隔，避免 TFT 波形刷新
         * 耗时较长时将 800 ms 长按误计为更短时间。
         */
        Button_Event_e next_event =
            ButtonProcess(next_button, button_elapsed_ms);
        Button_Event_e previous_event =
            ButtonProcess(previous_button, button_elapsed_ms);
        bool menu_changed = false;

        /* 页面分支使用 continue 隔离各自的按键和刷新逻辑，避免状态串页。 */
        /* 动作反馈是模态页面，显示期间暂停普通菜单和波形页面处理。 */
        if (action_feedback_active) {
            DisplayMenuProcessActionFeedback();
            vTaskDelayUntil(
                &next_wake_time, pdMS_TO_TICKS(DISPLAY_MENU_POLL_PERIOD_MS));
            continue;
        }

        /* 电赛自定义页独占显示；导航请求由本任务统一执行。 */
        if (custom_page_active) {
            CustomPageUpdate_e custom_page_update =
                CustomPageProcess(next_event, previous_event,
                    button_elapsed_ms);

            if (custom_page_update == CUSTOM_PAGE_UPDATE_EXIT_TO_MENU) {
                if (!DisplayMenuOpenFromCustom(
                        DISPLAY_MENU_ROUTE_MAIN_MENU)) {
                    (void)CustomPageSetStatus(CUSTOM_PAGE_STATUS_ERROR);
                    (void)CustomPageRender();
                }
            } else if (custom_page_update ==
                       CUSTOM_PAGE_UPDATE_REDRAW) {
                (void)CustomPageRender();
            }

            vTaskDelayUntil(
                &next_wake_time, pdMS_TO_TICKS(DISPLAY_MENU_POLL_PERIOD_MS));
            continue;
        }

#if APP_ENABLE_UART3 != 0U
        if (uart3_text_active) {
            DisplayMenuProcessUART3TextPage(next_event, previous_event);
            vTaskDelayUntil(
                &next_wake_time, pdMS_TO_TICKS(DISPLAY_MENU_POLL_PERIOD_MS));
            continue;
        }
#endif

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
        /* 整帧波形页独占按键和快照处理，退出后再回到普通菜单。 */
        if (waveform_active) {
            DisplayMenuHandleWaveformButtons(next_event, previous_event);
            if (waveform_active) {
                DisplayMenuProcessWaveform();
            }

            vTaskDelayUntil(
                &next_wake_time, pdMS_TO_TICKS(DISPLAY_MENU_POLL_PERIOD_MS));
            continue;
        }
#endif

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
        /* 同步相位页独占按键；左键短按回到 FFT 图，长按重新测量。 */
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
        if (phase_active) {
            DisplayMenuHandlePhaseButtons(next_event, previous_event);
            if (phase_active && DisplayMenuProcessSynchronizedPhase()) {
                (void)DisplayMenuRenderSynchronizedPhase();
            }

            vTaskDelayUntil(
                &next_wake_time, pdMS_TO_TICKS(DISPLAY_MENU_POLL_PERIOD_MS));
            continue;
        }
#endif

        /* 频谱页面与波形页面相同，也采用独立的页面处理状态机。 */
        if (spectrum_active) {
            DisplayMenuHandleSpectrumButtons(next_event, previous_event);
            if (spectrum_active && DisplayMenuProcessSpectrum()) {
                /* 状态处理返回后再刷新，避免 FFT 临时栈与 TFT 调用栈叠加。 */
                (void)DisplayMenuRenderSpectrum();
            }

            vTaskDelayUntil(
                &next_wake_time, pdMS_TO_TICKS(DISPLAY_MENU_POLL_PERIOD_MS));
            continue;
        }
#endif

        /* 普通菜单中：下一键短按移动、长按确认。 */
        if (next_event == BUTTON_EVENT_SHORT_PRESS) {
            menu_changed = MenuMoveNext(menu);
        } else if (next_event == BUTTON_EVENT_LONG_PRESS) {
            menu_changed = MenuSelect(menu);
        }

        /* 上一键短按反向移动、长按返回；动作回调启动反馈后不再处理。 */
        if (!action_feedback_active) {
            if (previous_event == BUTTON_EVENT_SHORT_PRESS) {
                menu_changed = MenuMovePrevious(menu) || menu_changed;
            } else if (previous_event == BUTTON_EVENT_LONG_PRESS) {
                if ((display_menu_return_target ==
                        DISPLAY_MENU_RETURN_CUSTOM_PAGE) &&
                    (MenuGetDepth(menu) <= display_menu_return_depth)) {
                    DisplayMenuReturnFromCurrentPage();
                } else {
                    menu_changed = MenuBack(menu) || menu_changed;
                }
            }
        }

        /* 处理对比度按键长按连调，不需要菜单重新创建。 */
        DisplayMenuProcessContrastRepeat();

        /* 页面内容发生变化时才刷新屏幕，减少不必要的总线传输。 */
        if (menu_changed
            && !custom_page_active
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
            && !waveform_active
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
            && !spectrum_active
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
            && !phase_active
#endif
#endif
        ) {
            if (action_feedback_active) {
                (void)DisplayMenuRenderActionFeedback();
            } else {
                (void)MenuRender(menu);
            }
        }

        vTaskDelayUntil(
            &next_wake_time, pdMS_TO_TICKS(DISPLAY_MENU_POLL_PERIOD_MS));
    }
}

/* 从主菜单进入与上电初始页相同的电赛自定义界面。 */
static void DisplayMenuActionStartCustomPage(void *context)
{
    (void)context;
    display_menu_return_target = DISPLAY_MENU_RETURN_MAIN_MENU;
    display_menu_return_depth = 0U;
    custom_page_active = true;
    if (!CustomPageEnter()) {
        custom_page_active = false;
        DisplayMenuSetActionFeedback("CUSTOM PAGE", false);
    }
}

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
/* 从菜单选择 PA27、PA21 或 UART2 后进入实时频谱页面。 */
#if APP_ENABLE_WAVEFORM_PA27 != 0U
static void DisplayMenuActionStartFFT27(void *context)
{
    (void)context;
    (void)WaveformMeasurementSetInput(
        WAVEFORM_MEASUREMENT_INPUT_PA27);
    DisplayMenuStartSpectrum(FFT_ANALYSIS_INPUT_PA27);
    (void)DisplayMenuRequestSpectrumMeasurement(
        FFT_ANALYSIS_INPUT_PA27, false);
    (void)DisplayMenuRenderSpectrum();
}
#endif

#if APP_ENABLE_WAVEFORM_PA21 != 0U
static void DisplayMenuActionStartFFT21(void *context)
{
    (void)context;
    (void)WaveformMeasurementSetInput(
        WAVEFORM_MEASUREMENT_INPUT_PA21);
    DisplayMenuStartSpectrum(FFT_ANALYSIS_INPUT_PA21);
    (void)DisplayMenuRequestSpectrumMeasurement(
        FFT_ANALYSIS_INPUT_PA21, false);
    (void)DisplayMenuRenderSpectrum();
}
#endif

#if APP_ENABLE_UART2 != 0U
static void DisplayMenuActionStartFFTUART2(void *context)
{
    (void)context;
    DisplayMenuStartSpectrum(FFT_ANALYSIS_INPUT_UART2);
    (void)DisplayMenuRequestSpectrumMeasurement(
        FFT_ANALYSIS_INPUT_UART2, false);
    (void)DisplayMenuRenderSpectrum();
}
#endif

#if APP_ENABLE_UART3_SPECTRUM != 0U
static void DisplayMenuActionStartFFTUART3(void *context)
{
    if (context != NULL) {
        uart3_spectrum_data_type =
            *(SerialCommunicationUART3DataType_e *)context;
    }
    DisplayMenuStartSpectrum(FFT_ANALYSIS_INPUT_UART3);
    (void)DisplayMenuRequestSpectrumMeasurement(
        FFT_ANALYSIS_INPUT_UART3, true);
    (void)DisplayMenuRenderSpectrum();
}
#endif

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
/* 进入双路同步相位页；结果定义为 PB19 相对 PA27。 */
static void DisplayMenuActionStartSynchronizedPhase(void *context)
{
    (void)context;
    phase_active = true;
    phase_request_active = false;
    phase_request_failed = false;
    phase_request_failure_status = WAVEFORM_MEASUREMENT_REQUEST_IDLE;
    (void)DisplayMenuRequestSynchronizedPhase();
    (void)DisplayMenuRenderSynchronizedPhase();
}

static bool DisplayMenuRequestSynchronizedPhase(void)
{
    phase_previous_sequence = UINT32_MAX;
    if (WaveformMeasurementCopyLatestSynchronizedPhase(&phase_result)) {
        phase_previous_sequence = phase_result.sequence;
    }
    phase_request_failed = false;
    phase_request_failure_status = WAVEFORM_MEASUREMENT_REQUEST_IDLE;

    if (WaveformMeasurementIsInputPending(
            WAVEFORM_MEASUREMENT_INPUT_PA27) ||
        WaveformMeasurementIsInputPending(
            WAVEFORM_MEASUREMENT_INPUT_PB19)) {
        phase_request_active = true;
        return true;
    }
    if (!WaveformMeasurementRequestSynchronizedPhase()) {
        if (WaveformMeasurementIsInputPending(
                WAVEFORM_MEASUREMENT_INPUT_PA27) ||
            WaveformMeasurementIsInputPending(
                WAVEFORM_MEASUREMENT_INPUT_PB19)) {
            phase_request_active = true;
            return true;
        }
        phase_request_active = false;
        phase_request_failed = true;
        phase_request_failure_status =
            WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
        return false;
    }
    phase_request_active = true;
    return true;
}

static void DisplayMenuHandlePhaseButtons(Button_Event_e left_event,
    Button_Event_e right_event)
{
    if (left_event == BUTTON_EVENT_SHORT_PRESS) {
        /* 相位结果完成后返回 PA27 FFT 图，再可继续循环切换来源。 */
        phase_active = false;
        spectrum_active = true;
        DisplayMenuActionStartFFT27(NULL);
        return;
    }
    if ((left_event == BUTTON_EVENT_LONG_PRESS) &&
        !phase_request_active) {
        (void)DisplayMenuRequestSynchronizedPhase();
        (void)DisplayMenuRenderSynchronizedPhase();
    }
    if (right_event == BUTTON_EVENT_LONG_PRESS) {
        phase_active = false;
        DisplayMenuReturnFromCurrentPage();
    }
}

static bool DisplayMenuProcessSynchronizedPhase(void)
{
    WaveformMeasurementRequestStatus_e pa27_status;
    WaveformMeasurementRequestStatus_e pb19_status;

    if (!phase_request_active) {
        return false;
    }
    if (WaveformMeasurementIsInputPending(
            WAVEFORM_MEASUREMENT_INPUT_PA27) ||
        WaveformMeasurementIsInputPending(
            WAVEFORM_MEASUREMENT_INPUT_PB19)) {
        return false;
    }

    pa27_status = WaveformMeasurementGetRequestStatus(
        WAVEFORM_MEASUREMENT_INPUT_PA27);
    pb19_status = WaveformMeasurementGetRequestStatus(
        WAVEFORM_MEASUREMENT_INPUT_PB19);
    if ((pa27_status != WAVEFORM_MEASUREMENT_REQUEST_COMPLETE) ||
        (pb19_status != WAVEFORM_MEASUREMENT_REQUEST_COMPLETE)) {
        phase_request_active = false;
        phase_request_failed = true;
        phase_request_failure_status =
            (pa27_status != WAVEFORM_MEASUREMENT_REQUEST_COMPLETE)
                ? pa27_status
                : pb19_status;
        return true;
    }
    if (!WaveformMeasurementCopyLatestSynchronizedPhase(&phase_result) ||
        (phase_result.sequence == phase_previous_sequence)) {
        phase_request_active = false;
        phase_request_failed = true;
        phase_request_failure_status =
            WAVEFORM_MEASUREMENT_REQUEST_CALCULATION_FAILED;
        return true;
    }

    phase_request_active = false;
    phase_request_failed = false;
    return true;
}

static bool DisplayMenuRenderSynchronizedPhase(void)
{
    const char *request_label;
    char frequency_label[11];
    char phase_label[14];
    uint32_t display_frequency_millihz;

    if (phase_request_active) {
        request_label = "WAIT";
    } else if (!phase_request_failed) {
        request_label = "DONE";
    } else if (phase_request_failure_status ==
               WAVEFORM_MEASUREMENT_REQUEST_START_FAILED) {
        request_label = "START";
    } else if (phase_request_failure_status ==
               WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT) {
        request_label = "TIME";
    } else {
        request_label = "ERROR";
    }

    if (!DisplayClear(menu_display, false) ||
        !DisplayDrawString(menu_display, 0U, 0U, "PHASE 19-27") ||
        !DisplayDrawString(menu_display, 78U, 0U, request_label)) {
        return false;
    }
    if (phase_request_active) {
        return DisplayDrawString(menu_display, 18U, 32U,
                   "WAITING PAIR") &&
               DisplayUpdate(menu_display);
    }
    if (phase_request_failed) {
        return DisplayDrawString(menu_display, 24U, 32U,
                   "MEASURE ERROR") &&
               DisplayUpdate(menu_display);
    }

    switch (phase_result.status) {
        case WAVEFORM_SYNCHRONIZED_PHASE_STATUS_VALID:
            display_frequency_millihz = phase_result.frequency_millihz;
            (void)WaveformMeasurementScaleInputFrequencyMillihz(
                WAVEFORM_MEASUREMENT_INPUT_PA27,
                phase_result.frequency_millihz,
                &display_frequency_millihz);
            DisplayMenuFormatFrequency(display_frequency_millihz,
                'F', frequency_label, sizeof(frequency_label));
            DisplayMenuFormatPhase(phase_result.phase_millidegrees,
                phase_label, sizeof(phase_label));
            return DisplayDrawString(
                       menu_display, 8U, 20U, frequency_label) &&
                   DisplayDrawString(
                       menu_display, 8U, 40U, phase_label) &&
                   DisplayUpdate(menu_display);

        case WAVEFORM_SYNCHRONIZED_PHASE_STATUS_NO_SIGNAL:
            return DisplayDrawString(menu_display, 24U, 32U,
                       "NO SIGNAL") &&
                   DisplayUpdate(menu_display);

        case WAVEFORM_SYNCHRONIZED_PHASE_STATUS_FREQUENCY_MISMATCH:
            return DisplayDrawString(menu_display, 12U, 24U,
                       "FREQ MISMATCH") &&
                   DisplayDrawString(menu_display, 8U, 44U,
                       "CHECK BOTH INPUTS") &&
                   DisplayUpdate(menu_display);

        case WAVEFORM_SYNCHRONIZED_PHASE_STATUS_CALCULATION_FAILED:
            return DisplayDrawString(menu_display, 24U, 32U,
                       "PHASE ERROR") &&
                   DisplayUpdate(menu_display);

        case WAVEFORM_SYNCHRONIZED_PHASE_STATUS_NOT_READY:
        default:
            return DisplayDrawString(menu_display, 24U, 32U,
                       "NOT READY") &&
                   DisplayUpdate(menu_display);
    }
}
#endif

/* 进入频谱页时清除旧请求状态，首次采集由调用动作显式发起。 */
static void DisplayMenuStartSpectrum(FFTAnalysisInput_e input)
{
    spectrum_input           = input;
    spectrum_result_sequence = UINT32_MAX;
    spectrum_previous_sequence = UINT32_MAX;
    spectrum_request_active  = false;
    spectrum_request_failed  = false;
    spectrum_components_active = false;
    spectrum_component_page = 0U;
    spectrum_request_failure_status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;
    spectrum_active          = true;
}

/* 所有频谱来源都按次请求；本函数只更新状态，由调用方统一刷新一次。 */
static bool DisplayMenuRequestSpectrumMeasurement(
    FFTAnalysisInput_e input, bool prepare_uart3)
{
    WaveformMeasurementInput_e measurement_input;

    (void)prepare_uart3;

    spectrum_previous_sequence = UINT32_MAX;
    /* 复用静态显示结果读取旧序列，避免在菜单任务栈上复制完整多峰结果。 */
    if (FFTAnalysisCopyLatestResult(input, &spectrum_result)) {
        spectrum_previous_sequence = spectrum_result.sequence;
    }
    spectrum_result_sequence = UINT32_MAX;
    spectrum_request_failed = false;
    spectrum_components_active = false;
    spectrum_component_page = 0U;
    spectrum_request_failure_status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;

#if APP_ENABLE_UART3_SPECTRUM != 0U
    if (input == FFT_ANALYSIS_INPUT_UART3) {
        bool request_started = prepare_uart3
            ? SerialCommunicationUART3RequestPreparedData(
                  uart3_spectrum_data_type)
            : SerialCommunicationUART3RequestData(
                  uart3_spectrum_data_type);

        if (request_started) {
            spectrum_request_active = true;
            return true;
        }
        spectrum_request_active = false;
        spectrum_request_failed = true;
        spectrum_request_failure_status =
            WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
        return false;
    }
#endif

    if (input == FFT_ANALYSIS_INPUT_UART2) {
        spectrum_request_active = true;
        return true;
    }

    measurement_input = (input == FFT_ANALYSIS_INPUT_PA21)
                            ? WAVEFORM_MEASUREMENT_INPUT_PA21
                            : WAVEFORM_MEASUREMENT_INPUT_PA27;
    if (WaveformMeasurementIsInputPending(measurement_input)) {
        /* 复用同一输入正在进行的测量，完成后读取它发布的新 FFT。 */
        spectrum_request_active = true;
        return true;
    }
    if (!WaveformMeasurementRequestInput(measurement_input)) {
        /* 检查“查询后、请求前”由其他任务启动测量的窄竞争窗口。 */
        if (WaveformMeasurementIsInputPending(measurement_input)) {
            spectrum_request_active = true;
            return true;
        }
        spectrum_request_active = false;
        spectrum_request_failed = true;
        spectrum_request_failure_status =
            WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
        return false;
    }
    spectrum_request_active = true;
    return true;
}

/* 左键短按切换来源，长按重新测量；右键短按查看分量、长按退出。 */
static void DisplayMenuHandleSpectrumButtons(Button_Event_e next_event,
    Button_Event_e previous_event)
{
    if (next_event == BUTTON_EVENT_SHORT_PRESS) {
        FFTAnalysisInput_e next_input;

        if (spectrum_input == FFT_ANALYSIS_INPUT_PA27) {
#if APP_ENABLE_WAVEFORM_PA21 != 0U
            next_input = FFT_ANALYSIS_INPUT_PA21;
#elif APP_ENABLE_UART2 != 0U
            next_input = FFT_ANALYSIS_INPUT_UART2;
#elif APP_ENABLE_UART3_SPECTRUM != 0U
            next_input = FFT_ANALYSIS_INPUT_UART3;
#elif APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
            spectrum_active = false;
            spectrum_components_active = false;
            spectrum_component_page = 0U;
            DisplayMenuActionStartSynchronizedPhase(NULL);
            return;
#else
            next_input = FFT_ANALYSIS_INPUT_PA27;
#endif
        } else if (spectrum_input == FFT_ANALYSIS_INPUT_PA21) {
#if APP_ENABLE_UART2 != 0U
            next_input = FFT_ANALYSIS_INPUT_UART2;
#elif APP_ENABLE_UART3_SPECTRUM != 0U
            next_input = FFT_ANALYSIS_INPUT_UART3;
#elif APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
            spectrum_active = false;
            spectrum_components_active = false;
            spectrum_component_page = 0U;
            DisplayMenuActionStartSynchronizedPhase(NULL);
            return;
#elif APP_ENABLE_WAVEFORM_PA27 != 0U
            next_input = FFT_ANALYSIS_INPUT_PA27;
#else
            next_input = FFT_ANALYSIS_INPUT_PA21;
#endif
        } else if (spectrum_input == FFT_ANALYSIS_INPUT_UART2) {
#if APP_ENABLE_UART3_SPECTRUM != 0U
            next_input = FFT_ANALYSIS_INPUT_UART3;
#elif APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
            /* 最后一个频谱来源之后进入双路相位页面。 */
            spectrum_active = false;
            spectrum_components_active = false;
            spectrum_component_page = 0U;
            DisplayMenuActionStartSynchronizedPhase(NULL);
            return;
#elif APP_ENABLE_WAVEFORM_PA27 != 0U
            next_input = FFT_ANALYSIS_INPUT_PA27;
#elif APP_ENABLE_WAVEFORM_PA21 != 0U
            next_input = FFT_ANALYSIS_INPUT_PA21;
#else
            next_input = FFT_ANALYSIS_INPUT_UART2;
#endif
        } else {
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
            /* UART3 是最后一个频谱来源。 */
            SerialCommunicationUART3CancelRequest();
            spectrum_active = false;
            spectrum_components_active = false;
            spectrum_component_page = 0U;
            DisplayMenuActionStartSynchronizedPhase(NULL);
            return;
#elif APP_ENABLE_WAVEFORM_PA27 != 0U
            next_input = FFT_ANALYSIS_INPUT_PA27;
#elif APP_ENABLE_WAVEFORM_PA21 != 0U
            next_input = FFT_ANALYSIS_INPUT_PA21;
#elif APP_ENABLE_UART2 != 0U
            next_input = FFT_ANALYSIS_INPUT_UART2;
#else
            next_input = FFT_ANALYSIS_INPUT_UART3;
#endif
        }

#if APP_ENABLE_UART3_SPECTRUM != 0U
        if ((spectrum_input == FFT_ANALYSIS_INPUT_UART3) &&
            (next_input != FFT_ANALYSIS_INPUT_UART3)) {
            SerialCommunicationUART3CancelRequest();
        }
#endif
        spectrum_input           = next_input;
        spectrum_result_sequence = UINT32_MAX;
        spectrum_components_active = false;
        spectrum_component_page = 0U;
        if ((next_input == FFT_ANALYSIS_INPUT_PA27) ||
            (next_input == FFT_ANALYSIS_INPUT_PA21)) {
            (void)WaveformMeasurementSetInput(
                (next_input == FFT_ANALYSIS_INPUT_PA21)
                    ? WAVEFORM_MEASUREMENT_INPUT_PA21
                    : WAVEFORM_MEASUREMENT_INPUT_PA27);
        }
        (void)DisplayMenuRequestSpectrumMeasurement(
            next_input, next_input == FFT_ANALYSIS_INPUT_UART3);
        (void)DisplayMenuRenderSpectrum();
    } else if (next_event == BUTTON_EVENT_LONG_PRESS) {
        /* 长按只重测当前来源，不改变 PA27/PB19/UART2/UART3 选择。 */
        spectrum_components_active = false;
        spectrum_component_page = 0U;
#if APP_ENABLE_UART3_SPECTRUM != 0U
        if (spectrum_input == FFT_ANALYSIS_INPUT_UART3) {
            SerialCommunicationUART3CancelRequest();
        }
#endif
        (void)DisplayMenuRequestSpectrumMeasurement(
            spectrum_input,
            spectrum_input == FFT_ANALYSIS_INPUT_UART3);
        (void)DisplayMenuRenderSpectrum();
    }

    if (previous_event == BUTTON_EVENT_SHORT_PRESS) {
        size_t page_count =
            ((spectrum_result_sequence == UINT32_MAX) ||
             (spectrum_result.component_count == 0U))
                ? 1U
                : ((spectrum_input == FFT_ANALYSIS_INPUT_UART3)
                       ? spectrum_result.component_count
                       : ((spectrum_result.component_count +
                              DISPLAY_MENU_SPECTRUM_COMPONENT_ROWS - 1U) /
                             DISPLAY_MENU_SPECTRUM_COMPONENT_ROWS));

        if (!spectrum_components_active) {
            spectrum_components_active = true;
            spectrum_component_page = 0U;
        } else if (((size_t)spectrum_component_page + 1U) <
                   page_count) {
            ++spectrum_component_page;
        } else {
            spectrum_components_active = false;
            spectrum_component_page = 0U;
        }
        (void)DisplayMenuRenderSpectrum();
    } else if (previous_event == BUTTON_EVENT_LONG_PRESS) {
#if APP_ENABLE_UART3_SPECTRUM != 0U
        if (spectrum_input == FFT_ANALYSIS_INPUT_UART3) {
            SerialCommunicationUART3CancelRequest();
        }
#endif
        spectrum_active = false;
        spectrum_components_active = false;
        spectrum_component_page = 0U;
        DisplayMenuReturnFromCurrentPage();
    }
}

/* 更新频谱请求状态；返回 true 时由上层在本函数退出后统一刷新。 */
static bool DisplayMenuProcessSpectrum(void)
{
    bool measurement_finished = true;
    WaveformMeasurementRequestStatus_e measurement_status =
        WAVEFORM_MEASUREMENT_REQUEST_COMPLETE;

    if (!spectrum_request_active) {
        return false;
    }

    if ((spectrum_input == FFT_ANALYSIS_INPUT_PA27) ||
        (spectrum_input == FFT_ANALYSIS_INPUT_PA21)) {
        WaveformMeasurementInput_e input =
            (spectrum_input == FFT_ANALYSIS_INPUT_PA21)
                ? WAVEFORM_MEASUREMENT_INPUT_PA21
                : WAVEFORM_MEASUREMENT_INPUT_PA27;

        measurement_finished =
            !WaveformMeasurementIsInputPending(input);
        measurement_status =
            WaveformMeasurementGetRequestStatus(input);
    }

    if (!measurement_finished) {
        return false;
    }
    if (((spectrum_input == FFT_ANALYSIS_INPUT_PA27) ||
         (spectrum_input == FFT_ANALYSIS_INPUT_PA21)) &&
        (measurement_status !=
            WAVEFORM_MEASUREMENT_REQUEST_COMPLETE)) {
        spectrum_request_active = false;
        spectrum_request_failed = true;
        spectrum_request_failure_status = measurement_status;
        return true;
    }
    /* 直接写入静态结果，避免在显示任务栈上复制完整多峰结果。 */
    if (!FFTAnalysisCopyLatestResult(spectrum_input, &spectrum_result) ||
        (spectrum_result.input != spectrum_input) ||
        (spectrum_result.sequence == spectrum_previous_sequence)) {
        if (spectrum_input == FFT_ANALYSIS_INPUT_UART2) {
            return false;
        }
#if APP_ENABLE_UART3_SPECTRUM != 0U
        if (spectrum_input == FFT_ANALYSIS_INPUT_UART3) {
            SerialCommunicationUART3TransactionStatus_e transaction_status =
                SerialCommunicationUART3GetTransactionStatus();

            if ((transaction_status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL) ||
                (transaction_status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP) ||
                (transaction_status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_COLLECTING)) {
                return false;
            }
            spectrum_request_active = false;
            spectrum_request_failed = true;
            spectrum_request_failure_status =
                (transaction_status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_TIMEOUT)
                    ? WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT
                    : WAVEFORM_MEASUREMENT_REQUEST_FFT_FAILED;
            return true;
        }
#endif
        /* ADC 测量的 FFT 在 COMPLETE 之前同步发布；此时仍无新结果即为异常。 */
        spectrum_request_active = false;
        spectrum_request_failed = true;
        spectrum_request_failure_status =
            WAVEFORM_MEASUREMENT_REQUEST_FFT_FAILED;
        return true;
    }

    spectrum_result_sequence = spectrum_result.sequence;
    spectrum_request_active  = false;
    spectrum_request_failed  = false;
    return true;
}

/* 根据去直流配置绘制 bin0～31 或 bin1～32，并显示交流主峰整数 Hz。 */
static bool DisplayMenuRenderSpectrum(void)
{
    /* Hz档最长P:999999HZ；MHz档使用P:2.000MHZ，均需11字节。 */
    char frequency_label[11];
    const char *request_status_label;
    uint32_t display_peak_frequency_millihz;
    uint16_t maximum_magnitude = 0U;
    uint8_t baseline_y = DISPLAY_HEIGHT - 1U;
    size_t bar;
    uint8_t x;

    if (spectrum_components_active) {
        return DisplayMenuRenderSpectrumComponents();
    }

    if (spectrum_request_active) {
#if APP_ENABLE_UART3_SPECTRUM != 0U
        SerialCommunicationUART3TransactionStatus_e uart3_status =
            (spectrum_input == FFT_ANALYSIS_INPUT_UART3)
                ? SerialCommunicationUART3GetTransactionStatus()
                : SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE;

        request_status_label =
            (uart3_status ==
                SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL)
                ? "PREP"
                : ((uart3_status ==
                       SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP)
                          ? "SWEEP"
                          : "WAIT");
#else
        request_status_label = "WAIT";
#endif
    } else if (!spectrum_request_failed) {
        request_status_label = "DONE";
    } else {
        switch (spectrum_request_failure_status) {
            case WAVEFORM_MEASUREMENT_REQUEST_START_FAILED:
                request_status_label = "START";
                break;
            case WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT:
                request_status_label = "TIME";
                break;
            case WAVEFORM_MEASUREMENT_REQUEST_FFT_FAILED:
                request_status_label = "FFTERR";
                break;
            case WAVEFORM_MEASUREMENT_REQUEST_CALCULATION_FAILED:
                request_status_label = "CALC";
                break;
            case WAVEFORM_MEASUREMENT_REQUEST_IDLE:
                request_status_label = "IDLE";
                break;
            case WAVEFORM_MEASUREMENT_REQUEST_COLLECTING:
                request_status_label = "BUSY";
                break;
            case WAVEFORM_MEASUREMENT_REQUEST_COMPLETE:
                request_status_label = "STALE";
                break;
            default:
                request_status_label = "STATE";
                break;
        }
    }

    if (!DisplayClear(menu_display, false) ||
        !DisplayDrawString(menu_display, 0U, 0U,
            (spectrum_input == FFT_ANALYSIS_INPUT_UART3)
                ? DisplayMenuGetUART3SpectrumLabel()
                : ((spectrum_input == FFT_ANALYSIS_INPUT_UART2)
                      ? "FFTU2"
                      : ((spectrum_input == FFT_ANALYSIS_INPUT_PA21)
                            ? "FFT19"
                            : "FFT27"))) ||
        !DisplayDrawString(menu_display, 36U, 0U,
            request_status_label)) {
        return false;
    }

    if (spectrum_result_sequence == UINT32_MAX) {
        return DisplayDrawString(menu_display, 24U, 32U, "WAITING FFT") &&
               DisplayUpdate(menu_display);
    }

    display_peak_frequency_millihz =
        spectrum_result.peak_frequency_millihz;
    if ((spectrum_input == FFT_ANALYSIS_INPUT_PA27) ||
        (spectrum_input == FFT_ANALYSIS_INPUT_PA21)) {
        WaveformMeasurementInput_e measurement_input =
            (spectrum_input == FFT_ANALYSIS_INPUT_PA21)
                ? WAVEFORM_MEASUREMENT_INPUT_PA21
                : WAVEFORM_MEASUREMENT_INPUT_PA27;

        if (!WaveformMeasurementScaleInputFrequencyMillihz(
                measurement_input,
                spectrum_result.peak_frequency_millihz,
                &display_peak_frequency_millihz)) {
            return false;
        }
    }
    DisplayMenuFormatFrequency(
        display_peak_frequency_millihz, 'P',
        frequency_label, sizeof(frequency_label));
    /* 从 x=66 开始可容纳完整六位 Hz，避免 100000 被截成 10000。 */
    if (!DisplayDrawString(menu_display, 66U, 0U, frequency_label)) {
        return false;
    }

    for (bar = 0U; bar < DISPLAY_MENU_SPECTRUM_BAR_COUNT; ++bar) {
        uint16_t magnitude = spectrum_result.magnitudes[
            DISPLAY_MENU_SPECTRUM_FIRST_BIN + bar];

        if (magnitude > maximum_magnitude) {
            maximum_magnitude = magnitude;
        }
    }

    for (x = 0U; x < DISPLAY_WIDTH; ++x) {
        (void)DisplaySetPixel(menu_display, x, baseline_y, true);
    }

    if (maximum_magnitude == 0U) {
        if (!DisplayDrawString(
                menu_display, 28U, 32U,
#if APP_FFT_REMOVE_DC == 0U
                "NO SIGNAL")) {
#else
                "NO AC SIGNAL")) {
#endif
            return false;
        }
    } else {
        for (bar = 0U; bar < DISPLAY_MENU_SPECTRUM_BAR_COUNT; ++bar) {
            uint16_t magnitude = spectrum_result.magnitudes[
                DISPLAY_MENU_SPECTRUM_FIRST_BIN + bar];
            uint8_t bar_height = (uint8_t)(
                ((uint32_t)magnitude *
                    (DISPLAY_MENU_SPECTRUM_PLOT_HEIGHT - 1U)) /
                maximum_magnitude);
            uint8_t bar_x = (uint8_t)(
                bar * DISPLAY_MENU_SPECTRUM_BAR_WIDTH);
            uint8_t column;
            uint8_t y;

            if ((magnitude > 0U) && (bar_height == 0U)) {
                bar_height = 1U;
            }
            for (column = 0U;
                 column < (DISPLAY_MENU_SPECTRUM_BAR_WIDTH - 1U);
                 ++column) {
                for (y = 0U; y < bar_height; ++y) {
                    (void)DisplaySetPixel(menu_display,
                        (uint8_t)(bar_x + column),
                        (uint8_t)(baseline_y - 1U - y), true);
                }
            }
        }
    }

    return DisplayUpdate(menu_display);
}

/* 本地 FFT 每页显示3个频率；UART3 每页显示1个峰值的频率和幅值。 */
static bool DisplayMenuRenderSpectrumComponents(void)
{
    char frequency_label[11];
    char amplitude_label[10];
    char page_label[4];
    size_t page_count;
    size_t first_component;
    size_t row;

    page_count = ((spectrum_result_sequence == UINT32_MAX) ||
                  (spectrum_result.component_count == 0U))
                     ? 1U
                     : ((spectrum_input == FFT_ANALYSIS_INPUT_UART3)
                            ? spectrum_result.component_count
                            : ((spectrum_result.component_count +
                                  DISPLAY_MENU_SPECTRUM_COMPONENT_ROWS - 1U) /
                                  DISPLAY_MENU_SPECTRUM_COMPONENT_ROWS));
    if ((size_t)spectrum_component_page >= page_count) {
        spectrum_component_page = 0U;
    }
    page_label[0] = (char)('1' + spectrum_component_page);
    page_label[1] = '/';
    page_label[2] = (char)('0' + page_count);
    page_label[3] = '\0';

    if (!DisplayClear(menu_display, false) ||
        !DisplayDrawString(menu_display, 0U, 0U,
            (spectrum_input == FFT_ANALYSIS_INPUT_UART3)
                ? DisplayMenuGetUART3SpectrumLabel()
                : ((spectrum_input == FFT_ANALYSIS_INPUT_UART2)
                      ? "FFTU2"
                      : ((spectrum_input == FFT_ANALYSIS_INPUT_PA21)
                            ? "FFT19"
                            : "FFT27"))) ||
        !DisplayDrawString(menu_display, 36U, 0U,
            (spectrum_input == FFT_ANALYSIS_INPUT_UART3)
                ? "PEAK"
                : "FREQ") ||
        !DisplayDrawString(menu_display, 102U, 0U, page_label)) {
        return false;
    }
    if (spectrum_result_sequence == UINT32_MAX) {
        return DisplayDrawString(menu_display, 18U, 32U,
                   "WAITING FFT") &&
               DisplayUpdate(menu_display);
    }
    if (spectrum_result.component_count == 0U) {
        return DisplayDrawString(menu_display, 18U, 32U,
                   "NO COMPONENT") &&
               DisplayUpdate(menu_display);
    }

    if (spectrum_input == FFT_ANALYSIS_INPUT_UART3) {
        size_t component_index = spectrum_component_page;

        DisplayMenuFormatFrequency(
            spectrum_result.components[component_index].frequency_millihz,
            'F', frequency_label, sizeof(frequency_label));
        DisplayMenuFormatAmplitudeMillivolts(
            spectrum_result.components[component_index].magnitude,
            amplitude_label, sizeof(amplitude_label));
        return DisplayDrawString(
                   menu_display, 8U, 22U, frequency_label) &&
               DisplayDrawString(
                   menu_display, 8U, 42U, amplitude_label) &&
               DisplayUpdate(menu_display);
    }

    first_component =
        (size_t)spectrum_component_page *
        DISPLAY_MENU_SPECTRUM_COMPONENT_ROWS;
    for (row = 0U; row < DISPLAY_MENU_SPECTRUM_COMPONENT_ROWS; ++row) {
        size_t component_index = first_component + row;
        uint32_t frequency_millihz;

        if (component_index >= spectrum_result.component_count) {
            break;
        }
        frequency_millihz = spectrum_result.components[
            component_index].frequency_millihz;
        if ((spectrum_input == FFT_ANALYSIS_INPUT_PA27) ||
            (spectrum_input == FFT_ANALYSIS_INPUT_PA21)) {
            WaveformMeasurementInput_e measurement_input =
                (spectrum_input == FFT_ANALYSIS_INPUT_PA21)
                    ? WAVEFORM_MEASUREMENT_INPUT_PA21
                    : WAVEFORM_MEASUREMENT_INPUT_PA27;

            if (!WaveformMeasurementScaleInputFrequencyMillihz(
                    measurement_input, frequency_millihz,
                    &frequency_millihz)) {
                return false;
            }
        }
        DisplayMenuFormatFrequency(frequency_millihz, 'F',
            frequency_label, sizeof(frequency_label));
        if (!DisplayDrawString(menu_display, 8U,
                (uint8_t)(16U + (row * 16U)), frequency_label)) {
            return false;
        }
    }
    return DisplayUpdate(menu_display);
}

static void DisplayMenuFormatFrequency(
    uint32_t frequency_millihz, char prefix,
    char *buffer, size_t capacity)
{
    uint32_t frequency_hz = (frequency_millihz + 500UL) / 1000UL;
    uint32_t divisor = 100000UL;
    size_t index = 0U;
    bool digit_started = false;

    /* 最长格式为P:xxxxxxHZ或P:x.xxxMHZ，加'\0'共需要11字节。 */
    if ((buffer == NULL) || (capacity < 11U)) {
        return;
    }

    buffer[index++] = prefix;
    buffer[index++] = ':';
    if ((frequency_hz >= 1000000UL) &&
        (frequency_hz < 10000000UL)) {
        uint32_t megahertz_milli =
            (frequency_hz + 500UL) / 1000UL;
        uint32_t fractional = megahertz_milli % 1000UL;

        buffer[index++] = (char)('0' + (megahertz_milli / 1000UL));
        buffer[index++] = '.';
        buffer[index++] = (char)('0' + (fractional / 100UL));
        buffer[index++] = (char)('0' + ((fractional / 10UL) % 10UL));
        buffer[index++] = (char)('0' + (fractional % 10UL));
        buffer[index++] = 'M';
        buffer[index++] = 'H';
        buffer[index++] = 'Z';
        buffer[index] = '\0';
        return;
    }
    while ((divisor > 0UL) && (index + 3U < capacity)) {
        uint32_t digit = frequency_hz / divisor;

        if ((digit > 0UL) || digit_started || (divisor == 1UL)) {
            buffer[index++] = (char)('0' + digit);
            digit_started = true;
        }
        frequency_hz %= divisor;
        divisor /= 10UL;
    }
    buffer[index++] = 'H';
    buffer[index++] = 'Z';
    buffer[index]   = '\0';
}

/* UART3 components 的幅值已在串口层从 V 换算成整数 mV。 */
static void DisplayMenuFormatAmplitudeMillivolts(
    uint16_t amplitude_millivolts, char *buffer, size_t capacity)
{
    uint32_t divisor = 10000UL;
    size_t index = 0U;
    bool digit_started = false;

    if ((buffer == NULL) || (capacity < 10U)) {
        return;
    }
    buffer[index++] = 'A';
    buffer[index++] = ':';
    while (divisor > 0UL) {
        uint32_t digit = amplitude_millivolts / divisor;

        if ((digit > 0UL) || digit_started || (divisor == 1UL)) {
            buffer[index++] = (char)('0' + digit);
            digit_started = true;
        }
        amplitude_millivolts = (uint16_t)(
            amplitude_millivolts % divisor);
        divisor /= 10UL;
    }
    buffer[index++] = 'M';
    buffer[index++] = 'V';
    buffer[index] = '\0';
}

#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
static void DisplayMenuFormatPhase(
    int32_t phase_millidegrees, char *buffer, size_t capacity)
{
    uint32_t absolute_phase;
    uint32_t degrees;
    uint32_t fraction;

    if ((buffer == NULL) || (capacity < 14U)) {
        return;
    }
    absolute_phase = (phase_millidegrees < 0)
                         ? (uint32_t)(-phase_millidegrees)
                         : (uint32_t)phase_millidegrees;
    degrees = absolute_phase / 1000UL;
    fraction = absolute_phase % 1000UL;

    buffer[0] = 'P';
    buffer[1] = ':';
    buffer[2] = (phase_millidegrees < 0) ? '-' : '+';
    buffer[3] = (char)('0' + ((degrees / 100UL) % 10UL));
    buffer[4] = (char)('0' + ((degrees / 10UL) % 10UL));
    buffer[5] = (char)('0' + (degrees % 10UL));
    buffer[6] = '.';
    buffer[7] = (char)('0' + (fraction / 100UL));
    buffer[8] = (char)('0' + ((fraction / 10UL) % 10UL));
    buffer[9] = (char)('0' + (fraction % 10UL));
    buffer[10] = 'D';
    buffer[11] = 'E';
    buffer[12] = 'G';
    buffer[13] = '\0';
}
#endif
#endif

/* 根据菜单应用调试开关决定是否通过 UART0 输出提示。 */
static void DisplayMenuDebugSend(const uint8_t *data, size_t size)
{
    if (DISPLAY_MENU_DEBUG_OUTPUT_ENABLED != 0U) {
        (void)SerialCommunicationUART0Send(data, size);
    }
}

/* 将当前显示屏切换为正常显示。 */
static void DisplayMenuActionNormal(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback(
        "DISPLAY NORMAL", DisplaySetInverted(menu_display, false));
}

/* 将当前显示屏切换为反色显示。 */
static void DisplayMenuActionInvert(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback(
        "DISPLAY INVERT", DisplaySetInverted(menu_display, true));
}

/* 以固定步长提高显示对比度/前景亮度，并执行上限饱和。 */
static void DisplayMenuActionContrastUp(void *context)
{
    (void)context;

    contrast_repeat_direction = DISPLAY_MENU_CONTRAST_REPEAT_UP;
    contrast_repeat_elapsed_ms = 0U;
    DisplayMenuAdjustContrast(true);
}

/* 以固定步长降低显示对比度/前景亮度，并执行下限饱和。 */
static void DisplayMenuActionContrastDown(void *context)
{
    (void)context;

    contrast_repeat_direction = DISPLAY_MENU_CONTRAST_REPEAT_DOWN;
    contrast_repeat_elapsed_ms = 0U;
    DisplayMenuAdjustContrast(false);
}

/* 按指定方向调整一级显示对比度/前景亮度。 */
static void DisplayMenuAdjustContrast(bool increase)
{
    if (increase) {
        display_contrast =
            (UINT8_MAX - display_contrast < DISPLAY_MENU_CONTRAST_STEP)
                ? UINT8_MAX
                : (uint8_t)(display_contrast + DISPLAY_MENU_CONTRAST_STEP);
    } else {
        display_contrast = (display_contrast < DISPLAY_MENU_CONTRAST_STEP)
                               ? 0U
                               : (uint8_t)(display_contrast -
                                          DISPLAY_MENU_CONTRAST_STEP);
    }

    (void)DisplaySetContrast(menu_display, display_contrast);
}

/* S1 保持按下时，按固定周期连续调整显示对比度/前景亮度。 */
static void DisplayMenuProcessContrastRepeat(void)
{
    bool pressed;

    if (contrast_repeat_direction == DISPLAY_MENU_CONTRAST_REPEAT_NONE) {
        return;
    }

    if (!ButtonIsPressed(next_button, &pressed) || !pressed) {
        contrast_repeat_direction = DISPLAY_MENU_CONTRAST_REPEAT_NONE;
        contrast_repeat_elapsed_ms = 0U;
        return;
    }

    contrast_repeat_elapsed_ms += DISPLAY_MENU_POLL_PERIOD_MS;
    if (contrast_repeat_elapsed_ms <
        DISPLAY_MENU_CONTRAST_REPEAT_PERIOD_MS) {
        return;
    }

    contrast_repeat_elapsed_ms = 0U;
    DisplayMenuAdjustContrast(
        contrast_repeat_direction == DISPLAY_MENU_CONTRAST_REPEAT_UP);
}

/* 保存动作结果，主任务随后绘制一个不会阻塞按键扫描的短暂提示页。 */
static void DisplayMenuSetActionFeedback(
    const char *label, bool success)
{
    if (label == NULL) {
        return;
    }

    action_feedback_label      = label;
    action_feedback_success    = success;
    action_feedback_elapsed_ms = 0UL;
    action_feedback_active     = true;
}

/* 提示保持指定时间后自动恢复执行动作前所在的菜单页面。 */
static void DisplayMenuProcessActionFeedback(void)
{
    action_feedback_elapsed_ms += DISPLAY_MENU_POLL_PERIOD_MS;
    if (action_feedback_elapsed_ms <
        DISPLAY_MENU_ACTION_FEEDBACK_PERIOD_MS) {
        return;
    }

    action_feedback_active     = false;
    action_feedback_label      = NULL;
    action_feedback_elapsed_ms = 0UL;
    if (custom_page_active) {
        (void)CustomPageResume();
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    } else if (waveform_active) {
        (void)DisplayMenuRenderWaveform(true);
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    } else if (spectrum_active) {
        (void)DisplayMenuRenderSpectrum();
#if APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U
    } else if (phase_active) {
        (void)DisplayMenuRenderSynchronizedPhase();
#endif
#endif
    } else {
        (void)MenuRender(menu);
    }
}

/* 显示动作名称及成功或失败状态，让无页面跳转操作具有明确反馈。 */
static bool DisplayMenuRenderActionFeedback(void)
{
    uint8_t x;

    if ((action_feedback_label == NULL) ||
        !DisplayClear(menu_display, false) ||
        !DisplayDrawString(menu_display, 0U, 0U, "ACTION RESULT")) {
        return false;
    }

    for (x = 0U; x < DISPLAY_WIDTH; ++x) {
        (void)DisplaySetPixel(menu_display, x, 9U, true);
    }

    return DisplayDrawString(
               menu_display, 8U, 24U, action_feedback_label) &&
           DisplayDrawString(menu_display, 8U, 40U,
               action_feedback_success ? "SUCCESS" : "FAILED") &&
           DisplayUpdate(menu_display);
}

/* 恢复正常显示和默认对比度。 */
static void DisplayMenuActionResetDisplay(void *context)
{
    bool inverted_result;
    bool contrast_result;

    (void)context;

    display_contrast = DISPLAY_MENU_DEFAULT_CONTRAST;
    inverted_result = DisplaySetInverted(menu_display, false);
    contrast_result = DisplaySetContrast(menu_display, display_contrast);
    DisplayMenuSetActionFeedback(
        "DISPLAY RESET", inverted_result && contrast_result);
}

/* 从 WAVEFORM 数据源页面采集并显示 PA27 ADC 整帧波形。 */
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 != 0U)
static void DisplayMenuActionStartADC27Waveform(void *context)
{
    (void)context;
    if (!DisplayMenuRequestADCMeasurement(
            WAVEFORM_MEASUREMENT_INPUT_PA27,
            DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA27, true)) {
        DisplayMenuSetActionFeedback("MEASURE PA27", false);
    }
}
#endif

/* 从 WAVEFORM 数据源页面采集并显示 PB19 / ADC1.6 整帧波形。 */
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
static void DisplayMenuActionStartADC21Waveform(void *context)
{
    (void)context;
    if (!DisplayMenuRequestADCMeasurement(
            WAVEFORM_MEASUREMENT_INPUT_PA21,
            DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21, true)) {
        DisplayMenuSetActionFeedback("MEASURE PB19", false);
    }
}
#endif

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
/* 保存旧序号后启动一次测量，确保波形页不会误显示上一次 DMA 数据块。 */
static bool DisplayMenuRequestADCMeasurement(
    WaveformMeasurementInput_e input,
    DisplayMenuWaveformSource_e source, bool start_page)
{
    WaveformMeasurement previous_result;

    if (WaveformMeasurementIsInputPending(input)) {
        return false;
    }

    if (start_page) {
        (void)WaveformMeasurementSetInput(input);
        DisplayMenuStartWaveform(source);
    }

    /* 每次请求都清空旧曲线，采集完整窗口前只显示 WAIT。 */
    (void)WaveformReset(waveform);
    waveform_adc_result_sequence = UINT32_MAX;
    if (WaveformMeasurementCopyLatestInput(input,
            &previous_result)) {
        waveform_adc_result_sequence = previous_result.sequence;
    }

    waveform_adc_request_failed = false;
    waveform_adc_request_failure_status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;
    if (!WaveformMeasurementRequestInput(input)) {
        waveform_adc_request_failed = true;
        waveform_adc_request_failure_status =
            WAVEFORM_MEASUREMENT_REQUEST_START_FAILED;
        waveform_adc_request_active = false;
        return false;
    }
    waveform_adc_request_active = true;
    (void)DisplayMenuRenderWaveform(true);
    return true;
}
#endif

/* 从 WAVEFORM 数据源页面开始收集 UART2 1024 点整帧波形。 */
#if APP_ENABLE_UART2 != 0U
static void DisplayMenuActionStartUART2Waveform(void *context)
{
    (void)context;
    DisplayMenuStartWaveform(DISPLAY_MENU_WAVEFORM_SOURCE_UART2);
}
#endif

/* 从 WAVEFORM 数据源页面开始收集 UART3 128 点整帧波形。 */
#if APP_ENABLE_UART3 != 0U
static void DisplayMenuActionStartUART3Waveform(void *context)
{
    if (context != NULL) {
        uart3_curve_data_type =
            *(SerialCommunicationUART3DataType_e *)context;
    }
    DisplayMenuStartWaveform(DISPLAY_MENU_WAVEFORM_SOURCE_UART3);
}
#endif

/* 从 DAC 菜单停止周期更新并关闭 PA15 模拟输出。 */
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U)
static void DisplayMenuActionStopDAC(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback(
        "DAC OUTPUT OFF", WaveformOutputDACStop());
}

/* 设置所选直流电压，成功后仅显示反馈，不切换到波形页面。 */
static void DisplayMenuActionSetDACDC(void *context)
{
    uint16_t *millivolts = (uint16_t *)context;
    bool result = (millivolts != NULL) &&
                  WaveformOutputDACSetMillivolts(*millivolts);

    /* 设置电压后显式开启 DAC；DAC 初始化时默认处于关闭状态。 */
    if (result) {
        result = WaveformOutputDACStart();
    }

    DisplayMenuSetActionFeedback("DAC DC LEVEL", result);
}

/* 将菜单中当前选择的上下限应用到周期波形配置。 */
static bool DisplayMenuApplyDACLimits(
    WaveformOutputDACConfig *config)
{
    if ((config == NULL) ||
        (dac_selected_minimum_millivolts >=
            dac_selected_maximum_millivolts) ||
        (dac_selected_maximum_millivolts > 3300U)) {
        return false;
    }
    config->minimum_millivolts = dac_selected_minimum_millivolts;
    config->maximum_millivolts = dac_selected_maximum_millivolts;
    return true;
}

/* 验证并保存上下限；周期波形正在输出时立即重配置。 */
static bool DisplayMenuSetDACLimits(
    uint16_t minimum_millivolts, uint16_t maximum_millivolts)
{
    WaveformOutputDACConfig active_config;
    WaveformOutputDACMode_e mode = WaveformOutputDACGetMode();
    bool periodic_output =
        (mode == WAVEFORM_OUTPUT_DAC_MODE_SINE) ||
        (mode == WAVEFORM_OUTPUT_DAC_MODE_SQUARE) ||
        (mode == WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE) ||
        (mode == WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH);
    bool result = (minimum_millivolts < maximum_millivolts) &&
                  (maximum_millivolts <= 3300U);

    if (result && periodic_output) {
        result = WaveformOutputDACGetConfig(&active_config);
        if (result) {
            active_config.minimum_millivolts = minimum_millivolts;
            active_config.maximum_millivolts = maximum_millivolts;
            result = WaveformOutputDACConfigure(&active_config);
        }
    }
    if (result) {
        dac_selected_minimum_millivolts = minimum_millivolts;
        dac_selected_maximum_millivolts = maximum_millivolts;
    }
    return result;
}

static void DisplayMenuActionSetDACLowerLimit(void *context)
{
    const uint16_t *minimum_millivolts = (const uint16_t *)context;
    bool result = (minimum_millivolts != NULL) &&
                  DisplayMenuSetDACLimits(*minimum_millivolts,
                      dac_selected_maximum_millivolts);

    DisplayMenuSetActionFeedback("DAC LOWER LIMIT", result);
}

static void DisplayMenuActionSetDACUpperLimit(void *context)
{
    const uint16_t *maximum_millivolts = (const uint16_t *)context;
    bool result = (maximum_millivolts != NULL) &&
                  DisplayMenuSetDACLimits(
                      dac_selected_minimum_millivolts,
                      *maximum_millivolts);

    DisplayMenuSetActionFeedback("DAC UPPER LIMIT", result);
}

/* 启动所选 DAC 周期波形，成功后仅显示反馈，不切换到波形页面。 */
static void DisplayMenuActionSetDACWaveform(void *context)
{
    const WaveformOutputDACConfig *config =
        (const WaveformOutputDACConfig *)context;
    WaveformOutputDACConfig requested_config;
    bool result = config != NULL;

    if (result) {
        requested_config = *config;
        result = DisplayMenuApplyDACLimits(&requested_config) &&
                 WaveformOutputDACConfigure(&requested_config);
    }

    DisplayMenuSetActionFeedback("DAC WAVEFORM", result);
}
#endif

#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
/* 播放所选 Flash 槽位；无效槽位或 DAC 参数异常时显示失败反馈。 */
static void DisplayMenuActionStartArbitraryWaveform(void *context)
{
    const uint8_t *slot_id = (const uint8_t *)context;
    const char *label;

    if ((slot_id == NULL) ||
        (*slot_id >= APP_ARBITRARY_WAVEFORM_SLOT_COUNT)) {
        DisplayMenuSetActionFeedback("SLOT INVALID", false);
        return;
    }

    /* 使用固定标签，避免把格式化缓冲区地址保存到反馈状态中。 */
    label = (*slot_id == 0U) ? "SLOT 0 PLAY" :
            ((*slot_id == 1U) ? "SLOT 1 PLAY" : "SLOT 2 PLAY");
    DisplayMenuSetActionFeedback(label,
        ArbitraryWaveformStart(*slot_id));
}

/* 关闭任意波形循环输出，但不擦除 Flash 槽位。 */
static void DisplayMenuActionStopArbitraryWaveform(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback("ARBITRARY OFF",
        ArbitraryWaveformStop());
}
#endif

#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
/* 菜单切换 PA27 触发模式；非关闭模式在空闲时从槽位0开始等待。 */
static void DisplayMenuActionSetPA27TriggerMode(void *context)
{
    const PA27ThresholdTriggerMode_e *mode =
        (const PA27ThresholdTriggerMode_e *)context;
    const char *label;
    bool result;

    if (mode == NULL) {
        DisplayMenuSetActionFeedback("PA27 MODE", false);
        return;
    }

    switch (*mode) {
        case PA27_THRESHOLD_TRIGGER_MODE_OFF:
            label = "PA27 OFF";
            break;
        case PA27_THRESHOLD_TRIGGER_MODE_SINGLE:
            label = "PA27 SINGLE";
            break;
        case PA27_THRESHOLD_TRIGGER_MODE_CONTINUOUS:
            label = "PA27 CONTINUOUS";
            break;
        default:
            DisplayMenuSetActionFeedback("PA27 MODE", false);
            return;
    }

    result = PA27ThresholdTriggerSetMode(*mode);
    if (result && (*mode != PA27_THRESHOLD_TRIGGER_MODE_OFF) &&
        !PA27ThresholdTriggerIsActive()) {
        result = PA27ThresholdTriggerArm(0U);
    }
    DisplayMenuSetActionFeedback(label, result);
}
#endif

#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
/* 从 PWM 菜单启动 PA23 PWM 输出。 */
static void DisplayMenuActionStartPWM(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback("PWM START", PWMOutputStart());
}

/* 从 PWM 菜单停止 PA23 PWM 输出。 */
static void DisplayMenuActionStopPWM(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback("PWM STOP", PWMOutputStop());
}

/* 将 PA23 PWM 切换到所选预设频率，并保持当前占空比。 */
static void DisplayMenuActionSetPWMFrequency(void *context)
{
    uint32_t *frequency_hz = (uint32_t *)context;
    bool result = (frequency_hz != NULL) &&
                  PWMOutputSetFrequency(*frequency_hz);

    DisplayMenuSetActionFeedback("PWM FREQUENCY", result);
}

/* 将 PA23 PWM 切换到所选预设占空比，并保持当前频率。 */
static void DisplayMenuActionSetPWMDutyCycle(void *context)
{
    uint8_t *duty_cycle_percent = (uint8_t *)context;
    bool result = (duty_cycle_percent != NULL) &&
                  PWMOutputSetDutyCycle(*duty_cycle_percent);

    DisplayMenuSetActionFeedback("PWM DUTY", result);
}
#endif

#if APP_ENABLE_WAVEFORM_MAPPING != 0U
/* 发起一次 PA27 测量；结果发布后由 Waveform Mapping 自动更新输出。 */
static void DisplayMenuActionRequestWaveformMapping(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback("MAP REQUEST",
        WaveformMeasurementRequestInput(
            WAVEFORM_MEASUREMENT_INPUT_PA27));
}

/* 停止当前配置选择的 AD9833 或 PA15 DAC 映射输出。 */
static void DisplayMenuActionStopWaveformMapping(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback(
        "MAP STOP", WaveformMappingStop());
}
#endif

/* 从 DDS 菜单恢复当前 AD9833 输出配置。 */
#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U)
static void DisplayMenuActionStartDDS(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback(
        "DDS START", WaveformOutputDDSStart());
}

/* 从 DDS 菜单将 AD9833 置于复位和休眠状态。 */
static void DisplayMenuActionStopDDS(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback(
        "DDS STOP", WaveformOutputDDSStop());
}

/* 将 AD9833 切换到所选正弦、三角或方波输出。 */
static void DisplayMenuActionSetDDSWaveform(void *context)
{
    WaveformOutputDDSWaveform_e *waveform_type =
        (WaveformOutputDDSWaveform_e *)context;
    bool result = (waveform_type != NULL) &&
                  WaveformOutputDDSSetWaveform(*waveform_type);

    DisplayMenuSetActionFeedback("DDS WAVEFORM", result);
}

/* 将 AD9833 切换到所选预设频率。 */
static void DisplayMenuActionSetDDSFrequency(void *context)
{
    uint32_t *frequency_hz = (uint32_t *)context;
    bool result = (frequency_hz != NULL) &&
                  WaveformOutputDDSSetFrequency(*frequency_hz);

    DisplayMenuSetActionFeedback("DDS FREQUENCY", result);
}

/* 将 AD9833 切换到所选预设相位。 */
static void DisplayMenuActionSetDDSPhase(void *context)
{
    uint16_t *phase_degrees = (uint16_t *)context;
    bool result = (phase_degrees != NULL) &&
                  WaveformOutputDDSSetPhase(*phase_degrees);

    DisplayMenuSetActionFeedback("DDS PHASE", result);
}
#endif

#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)
static void DisplayMenuActionStartAD9850(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback("AD9850 START",
        WaveformOutputAD9850Start());
}

static void DisplayMenuActionStopAD9850(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback("AD9850 STOP",
        WaveformOutputAD9850Stop());
}

static void DisplayMenuActionSetAD9850Waveform(void *context)
{
    WaveformOutputAD9850Waveform_e *waveform =
        (WaveformOutputAD9850Waveform_e *)context;
    bool result = (waveform != NULL) &&
                  WaveformOutputAD9850SetWaveform(*waveform);
    DisplayMenuSetActionFeedback("AD9850 PIN", result);
}

static void DisplayMenuActionSetAD9850Frequency(void *context)
{
    uint32_t *frequency_hz = (uint32_t *)context;
    bool result = (frequency_hz != NULL) &&
                  WaveformOutputAD9850SetFrequency(*frequency_hz);
    DisplayMenuSetActionFeedback("AD9850 FREQ", result);
}
#endif

/* 清空历史数据、恢复默认量程并首次绘制波形页面。 */
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
static void DisplayMenuStartWaveform(DisplayMenuWaveformSource_e source)
{
    /* 切换来源期间先拒绝异步串口提交，避免旧数据进入新缓冲区。 */
    taskENTER_CRITICAL();
    waveform_active = false;
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    waveform_frame_collecting = false;
#endif
    taskEXIT_CRITICAL();

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    waveform_range_index      = DisplayMenuIsADCWaveformSource(source)
                                    ? 2U
                                    : 1U;
#else
    waveform_range_index      = 1U;
#endif
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    waveform_frame_sample_count = 0U;
    waveform_frame_write_index = 0U;
    waveform_frame_ready = false;
    waveform_frame_failed = false;
    waveform_frame_timed_out = false;
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    waveform_adc_request_active = false;
    waveform_adc_request_failed = false;
    waveform_adc_request_failure_status =
        WAVEFORM_MEASUREMENT_REQUEST_IDLE;
#endif

    (void)WaveformReset(waveform);
    (void)WaveformSetRange(waveform,
        (int16_t)-waveform_ranges[waveform_range_index],
        waveform_ranges[waveform_range_index]);

    taskENTER_CRITICAL();
    waveform_source = source;
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    waveform_frame_collecting =
        (source == DISPLAY_MENU_WAVEFORM_SOURCE_UART2) ||
        (source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3);
#endif
    waveform_active = true;
    taskEXIT_CRITICAL();

#if (APP_ENABLE_UART3 != 0U) && \
    (APP_ENABLE_UART3_WAVEFORM_REQUEST != 0U)
    if ((source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) &&
        !SerialCommunicationUART3RequestPreparedData(
            uart3_curve_data_type)) {
        taskENTER_CRITICAL();
        waveform_frame_collecting = false;
        waveform_frame_failed = true;
        taskEXIT_CRITICAL();
    }
#endif

    (void)DisplayMenuRenderWaveform(true);
}
#endif

#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
/* UART2 收 1024 点并保留末尾窗口；UART3 收完整 128 点 ASCII 采样。 */
static bool DisplayMenuSubmitWaveformSampleForSource(
    DisplayMenuWaveformSource_e source, int16_t sample)
{
    bool accepted = false;
    size_t target_sample_count =
        DisplayMenuGetSerialWaveformSampleCount(source);

    if (target_sample_count == 0U) {
        return false;
    }

    taskENTER_CRITICAL();
    if (waveform_active &&
        (waveform_source == source) &&
        waveform_frame_collecting &&
        (waveform_frame_sample_count < target_sample_count)) {
        if (source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) {
            waveform_frame_samples[waveform_frame_sample_count] = sample;
            waveform_frame_write_index = waveform_frame_sample_count + 1U;
        } else {
            waveform_frame_samples[waveform_frame_write_index] = sample;
            waveform_frame_write_index =
                (waveform_frame_write_index + 1U) % DISPLAY_WIDTH;
        }
        ++waveform_frame_sample_count;
        accepted = true;

        if (waveform_frame_sample_count >= target_sample_count) {
            waveform_frame_collecting = false;
            waveform_frame_ready = true;
        }
    }
    taskEXIT_CRITICAL();
    return accepted;
}

/* 在串口页面上废弃旧快照，并按当前来源的固定点数重新采集。 */
static void DisplayMenuStartWaveformFrameCollection(bool prepare_uart3)
{
    taskENTER_CRITICAL();
    waveform_frame_sample_count = 0U;
    waveform_frame_write_index = 0U;
    waveform_frame_ready = false;
    waveform_frame_failed = false;
    waveform_frame_timed_out = false;
    waveform_frame_collecting = waveform_active &&
        ((waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART2) ||
         (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3));
    taskEXIT_CRITICAL();

    (void)WaveformReset(waveform);
#if (APP_ENABLE_UART3 != 0U) && \
    (APP_ENABLE_UART3_WAVEFORM_REQUEST != 0U)
    if (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) {
        bool request_started = prepare_uart3
            ? SerialCommunicationUART3RequestPreparedData(
                  uart3_curve_data_type)
            : SerialCommunicationUART3RequestData(uart3_curve_data_type);

        if (!request_started) {
            taskENTER_CRITICAL();
            waveform_frame_collecting = false;
            waveform_frame_failed = true;
            taskEXIT_CRITICAL();
        }
    }
#else
    (void)prepare_uart3;
#endif
    (void)DisplayMenuRenderWaveform(true);
}

/* 返回完成一帧所需的源点数，而不是最终 LCD 显示宽度。 */
static size_t DisplayMenuGetSerialWaveformSampleCount(
    DisplayMenuWaveformSource_e source)
{
    switch (source) {
        case DISPLAY_MENU_WAVEFORM_SOURCE_UART2:
#if APP_ENABLE_UART2 != 0U
            return DISPLAY_MENU_UART2_WAVEFORM_FRAME_SAMPLE_COUNT;
#else
            return 0U;
#endif

        case DISPLAY_MENU_WAVEFORM_SOURCE_UART3:
#if APP_ENABLE_UART3 != 0U
            return DISPLAY_MENU_UART3_WAVEFORM_FRAME_SAMPLE_COUNT;
#else
            return 0U;
#endif

        default:
            return 0U;
    }
}
#endif

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
/* 波形页左键短按调高量程、长按重新采集；右键短按循环切换来源。 */
static void DisplayMenuHandleWaveformButtons(Button_Event_e next_event,
    Button_Event_e previous_event)
{
    if (next_event == BUTTON_EVENT_SHORT_PRESS) {
        DisplayMenuChangeWaveformRange(true);
    } else if (next_event == BUTTON_EVENT_LONG_PRESS) {
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
        if (DisplayMenuIsADCWaveformSource(waveform_source)) {
            WaveformMeasurementInput_e input =
                (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21)
                    ? WAVEFORM_MEASUREMENT_INPUT_PA21
                    : WAVEFORM_MEASUREMENT_INPUT_PA27;

            if (!DisplayMenuRequestADCMeasurement(
                    input, waveform_source, false)) {
                waveform_adc_request_failed = true;
                (void)DisplayMenuRenderWaveform(true);
            }
        }
#endif
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
        if ((waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART2) ||
            (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3)) {
#if APP_ENABLE_UART3 != 0U
            if (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) {
                SerialCommunicationUART3CancelRequest();
            }
#endif
            DisplayMenuStartWaveformFrameCollection(
                waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3);
        }
#endif
    }

    if (previous_event == BUTTON_EVENT_SHORT_PRESS) {
        DisplayMenuSwitchWaveformSource();
    } else if (previous_event == BUTTON_EVENT_LONG_PRESS) {
#if APP_ENABLE_UART3 != 0U
        if (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) {
            SerialCommunicationUART3CancelRequest();
        }
#endif
        taskENTER_CRITICAL();
        waveform_active = false;
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
        waveform_frame_collecting = false;
        waveform_frame_ready = false;
#endif
        taskEXIT_CRITICAL();
        DisplayMenuReturnFromCurrentPage();
    }
}

/* 只在 ADC 测量完成或串口收满当前来源固定点数时生成并刷新一帧。 */
static void DisplayMenuProcessWaveform(void)
{
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    if (DisplayMenuIsADCWaveformSource(waveform_source)) {
        WaveformMeasurementInput_e input =
            (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21)
                ? WAVEFORM_MEASUREMENT_INPUT_PA21
                : WAVEFORM_MEASUREMENT_INPUT_PA27;

        if (waveform_adc_request_active &&
            !WaveformMeasurementIsInputPending(input)) {
            WaveformMeasurement result;
            WaveformMeasurementRequestStatus_e request_status =
                WaveformMeasurementGetRequestStatus(input);

            waveform_adc_request_active = false;
            waveform_adc_request_failure_status = request_status;
            waveform_adc_request_failed =
                (request_status !=
                    WAVEFORM_MEASUREMENT_REQUEST_COMPLETE) ||
                !WaveformMeasurementCopyLatestInput(input, &result) ||
                (result.sequence == waveform_adc_result_sequence);
            if (!waveform_adc_request_failed &&
                !DisplayMenuLoadADCWaveformSamples(input, &result)) {
                waveform_adc_request_failed = true;
            }
            if (!waveform_adc_request_failed) {
                waveform_adc_request_failure_status =
                    WAVEFORM_MEASUREMENT_REQUEST_IDLE;
            }
            (void)DisplayMenuRenderWaveform(true);
        }
        return;
    }
#endif

#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    if ((waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART2) ||
        (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3)) {
        bool frame_ready;
        size_t frame_sample_count;

#if APP_ENABLE_UART3 != 0U
        if ((waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) &&
            waveform_frame_collecting) {
            SerialCommunicationUART3TransactionStatus_e status =
                SerialCommunicationUART3GetTransactionStatus();

            if ((status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_REMOTE_ERROR) ||
                (status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR) ||
                (status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_TIMEOUT)) {
                taskENTER_CRITICAL();
                waveform_frame_collecting = false;
                waveform_frame_failed = true;
                waveform_frame_timed_out =
                    status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_TIMEOUT;
                taskEXIT_CRITICAL();
                (void)DisplayMenuRenderWaveform(true);
                return;
            }
        }
#endif

        taskENTER_CRITICAL();
        frame_ready = waveform_frame_ready;
        frame_sample_count = waveform_frame_sample_count;
        if (frame_ready) {
            waveform_frame_ready = false;
        }
        taskEXIT_CRITICAL();

        if (frame_ready) {
            waveform_frame_failed =
                (frame_sample_count !=
                    DisplayMenuGetSerialWaveformSampleCount(
                        waveform_source)) ||
                !DisplayMenuLoadCompletedSerialFrame();
            (void)DisplayMenuRenderWaveform(true);
        }
    }
#endif
}

/* UART3 直接装入完整 128 点；UART2 保持原来的最后 128 点显示方式。 */
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
static bool DisplayMenuLoadCompletedSerialFrame(void)
{
    size_t target_sample_count =
        DisplayMenuGetSerialWaveformSampleCount(waveform_source);
    size_t display_index;
#if APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC != 0U
    int32_t uart3_average = 0;
#endif

    if ((target_sample_count == 0U) ||
        (waveform_frame_sample_count != target_sample_count) ||
        !WaveformReset(waveform)) {
        return false;
    }

    if (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) {
#if APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC != 0U
        for (display_index = 0U; display_index < target_sample_count;
             ++display_index) {
            uart3_average += waveform_frame_samples[display_index];
        }
        uart3_average /= (int32_t)target_sample_count;
#endif

        for (display_index = 0U; display_index < DISPLAY_WIDTH;
             ++display_index) {
            size_t source_index =
                (display_index * (target_sample_count - 1U)) /
                (DISPLAY_WIDTH - 1U);
            int32_t display_sample = waveform_frame_samples[source_index];

#if APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC != 0U
            display_sample -= uart3_average;
            if (display_sample < INT16_MIN) {
                display_sample = INT16_MIN;
            } else if (display_sample > INT16_MAX) {
                display_sample = INT16_MAX;
            }
#endif

            if (!WaveformPushSample(
                    waveform, (int16_t)display_sample)) {
                return false;
            }
        }
    } else {
        size_t oldest_index = waveform_frame_write_index;

        for (display_index = 0U; display_index < DISPLAY_WIDTH;
             ++display_index) {
            if (!WaveformPushSample(waveform,
                    waveform_frame_samples[
                        (oldest_index + display_index) % DISPLAY_WIDTH])) {
                return false;
            }
        }
    }
    return true;
}
#endif

/* 测量完成后只复制窗口最后 128 点，保持原始样本值和时间顺序。 */
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
static bool DisplayMenuLoadADCWaveformSamples(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement)
{
    size_t expected_sample_count;
    size_t display_sample_count;
    size_t offset;

    expected_sample_count =
        WaveformMeasurementGetInputSampleCount(input);
    if ((measurement == NULL) || (expected_sample_count == 0U) ||
        (measurement->sample_count != expected_sample_count)) {
        return false;
    }

    display_sample_count =
        (measurement->sample_count < DISPLAY_WIDTH)
            ? measurement->sample_count
            : DISPLAY_WIDTH;
    offset = measurement->sample_count - display_sample_count;
    if (!WaveformReset(waveform)) {
        return false;
    }

    while (offset < measurement->sample_count) {
        size_t copied_count;
        size_t index;

        if (!WaveformMeasurementCopyLatestInputSamples(
                input, measurement->sequence, offset,
                waveform_adc_buffer, DISPLAY_MENU_ADC_COPY_CHUNK_SIZE,
                &copied_count) || (copied_count == 0U) ||
            (offset + copied_count > measurement->sample_count)) {
            return false;
        }
        for (index = 0U; index < copied_count; ++index) {
            if (!WaveformPushSample(waveform,
                    (int16_t)((int32_t)waveform_adc_buffer[index] -
                        2048))) {
                return false;
            }
        }
        offset += copied_count;
    }

    return true;
}

/* 判断当前来源是否为两路统一波形测量输入之一。 */
static bool DisplayMenuIsADCWaveformSource(DisplayMenuWaveformSource_e source)
{
    return (source == DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA27) ||
           (source == DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21);
}
#endif

/* 绘制页面标题和当前已完成的整帧曲线。 */
static bool DisplayMenuRenderWaveform(bool update_header)
{
    const char *status_label = "DONE";

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    if (DisplayMenuIsADCWaveformSource(waveform_source)) {
        if (waveform_adc_request_active) {
            status_label = "WAIT";
        } else if (!waveform_adc_request_failed) {
            status_label = "DONE";
        } else {
            switch (waveform_adc_request_failure_status) {
                case WAVEFORM_MEASUREMENT_REQUEST_START_FAILED:
                    status_label = "START";
                    break;
                case WAVEFORM_MEASUREMENT_REQUEST_TIMEOUT:
                    status_label = "TIME";
                    break;
                case WAVEFORM_MEASUREMENT_REQUEST_FFT_FAILED:
                    status_label = "FFTERR";
                    break;
                case WAVEFORM_MEASUREMENT_REQUEST_CALCULATION_FAILED:
                    status_label = "CALC";
                    break;
                case WAVEFORM_MEASUREMENT_REQUEST_IDLE:
                    status_label = "IDLE";
                    break;
                case WAVEFORM_MEASUREMENT_REQUEST_COLLECTING:
                    status_label = "BUSY";
                    break;
                case WAVEFORM_MEASUREMENT_REQUEST_COMPLETE:
                    status_label = "STALE";
                    break;
                default:
                    status_label = "STATE";
                    break;
            }
        }
    }
#endif
#if (APP_ENABLE_UART2 != 0U) || (APP_ENABLE_UART3 != 0U)
    if ((waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART2) ||
        (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3)) {
        if (waveform_frame_collecting) {
#if APP_ENABLE_UART3 != 0U
            SerialCommunicationUART3TransactionStatus_e uart3_status =
                (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3)
                    ? SerialCommunicationUART3GetTransactionStatus()
                    : SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE;

            status_label =
                (uart3_status ==
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL)
                    ? "PREP"
                    : ((uart3_status ==
                           SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP)
                              ? "SWEEP"
                              : "WAIT");
#else
            status_label = "WAIT";
#endif
        } else {
            status_label = waveform_frame_failed
                               ? (waveform_frame_timed_out
                                     ? "TIME"
                                     : "ERROR")
                               : "DONE";
        }
    }
#endif
    if (update_header) {
        if (!DisplayClear(menu_display, false) ||
            !DisplayDrawString(menu_display, 0U, 0U,
                DisplayMenuGetWaveformSourceLabel()) ||
            !DisplayDrawString(menu_display, 36U, 0U,
                status_label) ||
            !DisplayDrawString(menu_display, 72U, 0U,
                waveform_range_labels[waveform_range_index]) ||
            !DisplayDrawString(menu_display, 98U, 0U,
                DisplayMenuGetWaveformFrameLabel())) {
            return false;
        }
    }

    if (!WaveformRender(waveform)) {
        return false;
    }

    return update_header
               ? DisplayUpdate(menu_display)
               : DisplayUpdatePages(menu_display,
                     DISPLAY_MENU_WAVEFORM_FIRST_PAGE,
                     DISPLAY_MENU_WAVEFORM_PAGE_COUNT);
}

/* 循环切换 ±500、±1000、±2000 和 ±4000 四档输入量程。 */
static void DisplayMenuChangeWaveformRange(bool next_range)
{
    if (next_range) {
        waveform_range_index = (uint8_t)((waveform_range_index + 1U) %
                                         DISPLAY_MENU_WAVEFORM_RANGE_COUNT);
    } else {
        waveform_range_index = (waveform_range_index == 0U)
                                   ? DISPLAY_MENU_WAVEFORM_RANGE_COUNT - 1U
                                   : waveform_range_index - 1U;
    }

    (void)WaveformSetRange(waveform,
        (int16_t)-waveform_ranges[waveform_range_index],
        waveform_ranges[waveform_range_index]);
    (void)DisplayMenuRenderWaveform(true);
}

/*
 * 返回下一个编译配置中已启用的波形来源。
 *
 * 来源枚举的顺序固定为 PA27、PB19、UART2、UART3，右键短按按此顺序循环。
 * ADC 正在采集时 FFT 工作区仍被占用，不能同时启动另一路 ADC；此时保持
 * 当前来源，待本次状态从 WAIT 变为 DONE/错误后再切换即可。
 */
static void DisplayMenuSwitchWaveformSource(void)
{
    DisplayMenuWaveformSource_e next_source = waveform_source;
    uint32_t offset;

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    if (waveform_adc_request_active) {
        return;
    }
#endif

    for (offset = 1U;
         offset < (uint32_t)DISPLAY_MENU_WAVEFORM_SOURCE_COUNT;
         ++offset) {
        DisplayMenuWaveformSource_e candidate =
            (DisplayMenuWaveformSource_e)(((uint32_t)waveform_source +
                offset) %
                (uint32_t)DISPLAY_MENU_WAVEFORM_SOURCE_COUNT);

        if (DisplayMenuIsWaveformSourceEnabled(candidate)) {
            next_source = candidate;
            break;
        }
    }

    /* 仅启用一个来源时短按右键无副作用。 */
    if (next_source == waveform_source) {
        return;
    }

#if APP_ENABLE_UART3 != 0U
    if (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) {
        SerialCommunicationUART3CancelRequest();
    }
#endif

    switch (next_source) {
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 != 0U)
        case DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA27:
            (void)DisplayMenuRequestADCMeasurement(
                WAVEFORM_MEASUREMENT_INPUT_PA27, next_source, true);
            break;
#endif
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
        case DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21:
            (void)DisplayMenuRequestADCMeasurement(
                WAVEFORM_MEASUREMENT_INPUT_PA21, next_source, true);
            break;
#endif
#if APP_ENABLE_UART2 != 0U
        case DISPLAY_MENU_WAVEFORM_SOURCE_UART2:
            DisplayMenuStartWaveform(next_source);
            break;
#endif
#if APP_ENABLE_UART3 != 0U
        case DISPLAY_MENU_WAVEFORM_SOURCE_UART3:
            DisplayMenuStartWaveform(next_source);
            break;
#endif
        default:
            break;
    }
}

/* 判断该来源是否已通过 app_config.h 编译进当前固件。 */
static bool DisplayMenuIsWaveformSourceEnabled(
    DisplayMenuWaveformSource_e source)
{
    switch (source) {
        case DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA27:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 != 0U)
            return true;
#else
            return false;
#endif

        case DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21:
#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 != 0U)
            return true;
#else
            return false;
#endif

        case DISPLAY_MENU_WAVEFORM_SOURCE_UART2:
#if APP_ENABLE_UART2 != 0U
            return true;
#else
            return false;
#endif

        case DISPLAY_MENU_WAVEFORM_SOURCE_UART3:
#if APP_ENABLE_UART3 != 0U
            return true;
#else
            return false;
#endif

        default:
            return false;
    }
}

/* 返回当前波形数据来源的短标题。 */
static const char *DisplayMenuGetWaveformSourceLabel(void)
{
    switch (waveform_source) {
        case DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA27:
            return "ADC27";

        case DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21:
            return "ADC19";

        case DISPLAY_MENU_WAVEFORM_SOURCE_UART2:
            return "UART2";

        case DISPLAY_MENU_WAVEFORM_SOURCE_UART3:
            return DisplayMenuGetUART3CurveLabel();

        default:
            return "UNKNOWN";
    }
}

#if APP_ENABLE_UART3 != 0U
/* 将 UART3 曲线命令映射为标题栏可容纳的短标签。 */
static const char *DisplayMenuGetUART3CurveLabel(void)
{
    switch (uart3_curve_data_type) {
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1:
            return "LWA1";
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A3:
            return "LWA3";
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B1:
            return "LWB1";
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B3:
            return "LWB3";
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_1:
            return "LW1";
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_3:
            return "LW3";
        case SERIAL_COMMUNICATION_UART3_DATA_LAFC:
            return "LAFC";
        case SERIAL_COMMUNICATION_UART3_DATA_LPFC:
            return "LPFC";
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A1:
            return "WA1";
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A3:
            return "WA3";
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B1:
            return "WB1";
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B3:
            return "WB3";
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_1:
            return "W1";
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_3:
            return "W3";
        case SERIAL_COMMUNICATION_UART3_DATA_AFC:
            return "AFC";
        case SERIAL_COMMUNICATION_UART3_DATA_PFC:
            return "PFC";
        default:
            return "UART3";
    }
}
#endif

/* 将 UART3 频谱命令映射为标题栏可容纳的短标签。 */
static const char *DisplayMenuGetUART3SpectrumLabel(void)
{
#if APP_ENABLE_UART3_SPECTRUM != 0U
    switch (uart3_spectrum_data_type) {
        case SERIAL_COMMUNICATION_UART3_DATA_LSPECT_B:
            return "LSPB";
        case SERIAL_COMMUNICATION_UART3_DATA_SPECT_A:
            return "SPA";
        case SERIAL_COMMUNICATION_UART3_DATA_SPECT_B:
            return "SPB";
        case SERIAL_COMMUNICATION_UART3_DATA_SPECTRUM:
            return "SPEC";
        default:
            return "LSPA";
    }
#else
    return "FFTU3";
#endif
}

/* 显示本次完整采集点数。 */
static const char *DisplayMenuGetWaveformFrameLabel(void)
{
#if APP_ENABLE_UART2 != 0U
    if (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART2) {
        return "N1024";
    }
#endif
#if APP_ENABLE_UART3 != 0U
    if (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_UART3) {
        switch (uart3_curve_data_type) {
            case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A1:
            case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A3:
            case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B1:
            case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B3:
            case SERIAL_COMMUNICATION_UART3_DATA_WAVE_1:
            case SERIAL_COMMUNICATION_UART3_DATA_WAVE_3:
                return "N800";
            case SERIAL_COMMUNICATION_UART3_DATA_AFC:
            case SERIAL_COMMUNICATION_UART3_DATA_PFC:
                return "N496";
            default:
                return "N128";
        }
    }
#endif

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    {
        WaveformMeasurementInput_e input =
            (waveform_source == DISPLAY_MENU_WAVEFORM_SOURCE_ADC_PA21)
                ? WAVEFORM_MEASUREMENT_INPUT_PA21
                : WAVEFORM_MEASUREMENT_INPUT_PA27;

        switch (WaveformMeasurementGetInputSampleCount(input)) {
            case 64U:
                return "N64";
            case 128U:
                return "N128";
            case 256U:
                return "N256";
            case 512U:
                return "N512";
            case 1024U:
                return "N1024";
            case 2048U:
                return "N2048";
            default:
                return "N?";
        }
    }
#else
    return "N?";
#endif
}
#endif
