/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * File Name          : freertos.c
  * Description        : Code for freertos applications
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "FreeRTOS.h"
#include "task.h"
#include "main.h"
#include "cmsis_os.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN Variables */

/* USER CODE END Variables */
/* Definitions for defaultTask */
osThreadId_t defaultTaskHandle;
const osThreadAttr_t defaultTask_attributes = {
  .name = "defaultTask",
  .stack_size = 128 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN FunctionPrototypes */

/* USER CODE END FunctionPrototypes */

void StartDefaultTask(void *argument);

void MX_FREERTOS_Init(void); /* (MISRA C 2004 rule 8.1) */

/**
  * @brief  FreeRTOS initialization
  * @param  None
  * @retval None
  */
void MX_FREERTOS_Init(void) {
  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* USER CODE BEGIN RTOS_MUTEX */
  /* add mutexes, ... */
  /* USER CODE END RTOS_MUTEX */

  /* USER CODE BEGIN RTOS_SEMAPHORES */
  /* add semaphores, ... */
  /* USER CODE END RTOS_SEMAPHORES */

  /* USER CODE BEGIN RTOS_TIMERS */
  /* start timers, add new ones, ... */
  /* USER CODE END RTOS_TIMERS */

  /* USER CODE BEGIN RTOS_QUEUES */
  /* add queues, ... */
  /* USER CODE END RTOS_QUEUES */

  /* Create the thread(s) */
  /* creation of defaultTask */
  defaultTaskHandle = osThreadNew(StartDefaultTask, NULL, &defaultTask_attributes);

  /* USER CODE BEGIN RTOS_THREADS */
  /* add threads, ... */
  /* USER CODE END RTOS_THREADS */

  /* USER CODE BEGIN RTOS_EVENTS */
  /* add events, ... */
  /* USER CODE END RTOS_EVENTS */

}

/* USER CODE BEGIN Header_StartDefaultTask */

/* 创建USER_TASK任务相关参数 */
#define      USER_TASK_PRIO          26
#define      USER_TASK_STACK_SIZE    512
TaskHandle_t USER_TASK_handler;
void         USER_TASK( void * pvParameters );

/* ������ˢ���С�����������ز��� */
#define      BLDC_TASK_PRIO          38
#define      BLDC_TASK_STACK_SIZE    512
TaskHandle_t BLDC_TASK_handler;
void         BLDC_TASK( void * pvParameters );
/* 创建KEY_TASK任务相关参数 */
#define      KEY_TASK_PRIO          36
#define      KEY_TASK_STACK_SIZE    256
TaskHandle_t KEY_TASK_handler;
void         KEY_TASK( void * pvParameters );

/* 创建 OLED 显示任务 */
#define      OLED_Task_Name          "OLED_Task"
#define      OLED_Task_STACK_SIZE    512
#define      OLED_Task_PRIORITY      25
TaskHandle_t OLED_Task_Handle;
void         OLED_Task( void * pvParameters );

/* USER CODE END Header_StartDefaultTask */
void StartDefaultTask(void *argument)
{
  /* USER CODE BEGIN StartDefaultTask */
	taskENTER_CRITICAL();               /* 进入临界区，禁止任务调度，防止创建多任务过程中发生任务切�?*/
	
	/* 创建USER_TASK任务 */
	xTaskCreate ( USER_TASK, "USER_TASK", USER_TASK_STACK_SIZE, NULL, USER_TASK_PRIO, &USER_TASK_handler );
	configASSERT( USER_TASK_handler );  /* 断言检测任务是否创建成�?*/
	
	/* ������ˢ���С��������� */
	xTaskCreate ( BLDC_TASK, "BLDC_TASK", BLDC_TASK_STACK_SIZE, NULL, BLDC_TASK_PRIO, &BLDC_TASK_handler );
	configASSERT( BLDC_TASK_handler );	
	/* 创建KEY_TASK任务 */
	xTaskCreate ( KEY_TASK, "KEY_TASK", KEY_TASK_STACK_SIZE, NULL, KEY_TASK_PRIO, &KEY_TASK_handler );
	configASSERT( KEY_TASK_handler );   /* 断言检测任务是否创建成�?*/
	
	/* 创建 OLED 显示任务 */
	xTaskCreate ( OLED_Task, OLED_Task_Name, OLED_Task_STACK_SIZE, NULL, OLED_Task_PRIORITY, &OLED_Task_Handle );
	configASSERT( OLED_Task_Handle );   /* 断言检测任务是否创建成�?*/
	
	/* 删除默认任务，本函数执行完成后不再保留默认任务句�?*/
	vTaskDelete(defaultTaskHandle);
	
	taskEXIT_CRITICAL();                /* 退出临界区，恢复任务调�?*/
	
  /* Infinite loop */
  for(;;)
  {
    osDelay(portMAX_DELAY);
  }
  /* USER CODE END StartDefaultTask */
}

/* Private application code --------------------------------------------------*/
/* USER CODE BEGIN Application */

/* USER CODE END Application */

