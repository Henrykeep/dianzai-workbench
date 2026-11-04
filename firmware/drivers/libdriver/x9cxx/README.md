[English](/README.md) | [ 简体中文](/README_zh-Hans.md) | [繁體中文](/README_zh-Hant.md) | [日本語](/README_ja.md) | [Deutsch](/README_de.md) | [한국어](/README_ko.md)

<div align=center>
<img src="/doc/image/logo.svg" width="400" height="150"/>
</div>

## LibDriver X9CXX

[![MISRA](https://img.shields.io/badge/misra-compliant-brightgreen.svg)](/misra/README.md) [![API](https://img.shields.io/badge/api-reference-blue.svg)](https://www.libdriver.com/docs/x9cxx/index.html) [![License](https://img.shields.io/badge/license-MIT-brightgreen.svg)](/LICENSE)

The X9C102, X9C103, X9C104, X9C503 are digitally controlled (XDCP) potentiometers. The device consists of a resistor array, wiper switches, a control section, and nonvolatile memory. The wiper position is controlled by a three-wire interface. The potentiometer is implemented by a resistor array composed of 99 resistive elements and a wiper switching network. Between each element and at either end are tap points accessible to the wiper terminal. The position of the wiper element is controlled by the CS, U/D, and INC inputs. The position of the wiper can be stored in non-volatile memory and then be recalled upon a subsequent power-up operation. The device can be used as a three-terminal potentiometer or as a two-terminal variable resistor in a wide variety of applications ranging from control to signal processing to parameter adjustment.

LibDriver X9CXX is a full-featured driver for X9CXX, launched by LibDriver. It provides digital potentiometer and additional features. LibDriver is MISRA compliant.

### Table of Contents

  - [Instruction](#Instruction)
  - [Install](#Install)
  - [Usage](#Usage)
    - [example basic](#example-basic)
  - [Document](#Document)
  - [Contributing](#Contributing)
  - [License](#License)
  - [Contact Us](#Contact-Us)

### Instruction

/src includes LibDriver X9CXX source files.

/interface includes LibDriver X9CXX GPIO platform independent template.

/test includes LibDriver X9CXX driver test code and this code can test the chip necessary function simply.

/example includes LibDriver X9CXX sample code.

/doc includes LibDriver X9CXX offline document.

/datasheet includes X9CXX datasheet.

/project includes the common Linux and MCU development board sample code. All projects use the shell script to debug the driver and the detail instruction can be found in each project's README.md.

/misra includes the LibDriver MISRA code scanning results.

### Install

Reference /interface GPIO platform independent template and finish your platform GPIO driver.

Add the /src directory, the interface driver for your platform, and your own drivers to your project, if you want to use the default example drivers, add the /example directory to your project.

### Usage

You can refer to the examples in the /example directory to complete your own driver. If you want to use the default programming examples, here's how to use them.

#### example basic

```C
#include "driver_x9cxx_basic.h"

uint8_t res;
uint8_t s;
uint8_t step = 5;
float ohm;
float resistor = 1000.0f;
x9cxx_bool_t store_enable = X9CXX_BOOL_FALSE;

/* basic */
res = x9cxx_basic_init(X9C102);
if (res != 0)
{
    return 1;
}

...
    
/* reset to max */
res = x9cxx_basic_reset_to_max(store_enable);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: reset to max failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* get resistor */
res = x9cxx_basic_get_resistor(&s, &ohm);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: get resistor failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* output */
x9cxx_interface_debug_print("x9cxx: reset to max.\n");
x9cxx_interface_debug_print("x9cxx: step is %d.\n", s);
x9cxx_interface_debug_print("x9cxx: resistor is %0.2fohm.\n", ohm);

...
    
/* reset to min */
res = x9cxx_basic_reset_to_min(store_enable);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: reset to min failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* get resistor */
res = x9cxx_basic_get_resistor(&s, &ohm);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: get resistor failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* output */
x9cxx_interface_debug_print("x9cxx: reset to min.\n");
x9cxx_interface_debug_print("x9cxx: step is %d.\n", s);
x9cxx_interface_debug_print("x9cxx: resistor is %0.2fohm.\n", ohm);

...
    
/* increment */
res = x9cxx_basic_increment(step, store_enable);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: increment failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* get resistor */
res = x9cxx_basic_get_resistor(&s, &ohm);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: get resistor failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* output */
x9cxx_interface_debug_print("x9cxx: increment %d step.\n", step);
x9cxx_interface_debug_print("x9cxx: step is %d.\n", s);
x9cxx_interface_debug_print("x9cxx: resistor is %0.2fohm.\n", ohm);   

...
 
/* decrement */
res = x9cxx_basic_decrement(step, store_enable);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: decrement failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* get resistor */
res = x9cxx_basic_get_resistor(&s, &ohm);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: get resistor failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* output */
x9cxx_interface_debug_print("x9cxx: decrement %d step.\n", step);
x9cxx_interface_debug_print("x9cxx: step is %d.\n", s);
x9cxx_interface_debug_print("x9cxx: resistor is %0.2fohm.\n", ohm); 

...

/* set absolute step */
res = x9cxx_basic_set_absolute_step(step, store_enable);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: set absolute step failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* get resistor */
res = x9cxx_basic_get_resistor(&s, &ohm);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: get resistor failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* output */
x9cxx_interface_debug_print("x9cxx: set absolute step %d.\n", step);
x9cxx_interface_debug_print("x9cxx: step is %d.\n", s);
x9cxx_interface_debug_print("x9cxx: resistor is %0.2fohm.\n", ohm);   

...

/* set absolute resistor */
res = x9cxx_basic_set_absolute_resistor(resistor, store_enable);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: set absolute resistor failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* get resistor */
res = x9cxx_basic_get_resistor(&s, &ohm);
if (res != 0)
{
    x9cxx_interface_debug_print("x9cxx: get resistor failed.\n");
    (void)x9cxx_basic_deinit();

    return 1;
}

/* output */
x9cxx_interface_debug_print("x9cxx: set absolute resistor %0.2fohm.\n", resistor);
x9cxx_interface_debug_print("x9cxx: step is %d.\n", s);
x9cxx_interface_debug_print("x9cxx: resistor is %0.2fohm.\n", ohm);   

...

(void)x9cxx_basic_deinit();

return 0;
```

### Document

Online documents: [https://www.libdriver.com/docs/x9cxx/index.html](https://www.libdriver.com/docs/x9cxx/index.html).

Offline documents: /doc/html/index.html.

### Contributing

Please refer to CONTRIBUTING.md.

### License

Copyright (c) 2015 - present LibDriver All rights reserved



The MIT License (MIT) 



Permission is hereby granted, free of charge, to any person obtaining a copy

of this software and associated documentation files (the "Software"), to deal

in the Software without restriction, including without limitation the rights

to use, copy, modify, merge, publish, distribute, sublicense, and/or sell

copies of the Software, and to permit persons to whom the Software is

furnished to do so, subject to the following conditions: 



The above copyright notice and this permission notice shall be included in all

copies or substantial portions of the Software. 



THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR

IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,

FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE

AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER

LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,

OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE

SOFTWARE. 

### Contact Us

Please send an e-mail to lishifenging@outlook.com.