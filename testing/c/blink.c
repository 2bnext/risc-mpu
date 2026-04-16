void main() {
	uint8_t gpio = 0;

	gpio_set_dir(0b1000_0000);	// 8 is output
	
	for (;;) {
		gpio = gpio ^ 0b1000_0000;
		gpio_write(gpio);
		sleep(500000);
	}
}
