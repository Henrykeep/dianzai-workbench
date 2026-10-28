void s(shared_state_t *st){ st->b_out.v = 1; float k = st->a_out.v; (void)k; if (st->a_out.v == 0) {} st->a_out.v += 2; }
