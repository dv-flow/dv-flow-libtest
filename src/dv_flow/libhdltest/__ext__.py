import os


def dvfm_packages():
    d = os.path.dirname(os.path.abspath(__file__))
    return {
        'hdltest': os.path.join(d, "flow.dv"),
        'hdltest.svunit': os.path.join(d, "svunit", "flow.dv"),
    }
