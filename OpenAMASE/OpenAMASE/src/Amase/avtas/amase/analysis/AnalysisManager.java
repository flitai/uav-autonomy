// ===============================================================================
// Authors: AFRL/RQQD
// Organization: Air Force Research Laboratory, Aerospace Systems Directorate, Power and Control Division
// 
// Copyright (c) 2017 Government of the United State of America, as represented by
// the Secretary of the Air Force.  No copyright is claimed in the United States under
// Title 17, U.S. Code.  All Other Rights Reserved.
// ===============================================================================

package avtas.amase.analysis;

import avtas.amase.AmasePlugin;
import avtas.amase.scenario.ScenarioEvent;
import avtas.amase.scenario.ScenarioState;
import avtas.amase.scenario.ScenarioState.EventWrapper;
import avtas.app.Context;
import avtas.app.ContextListener;
import avtas.app.UserExceptions;
import avtas.swing.UserNotice;
import avtas.xml.XMLUtil;
import avtas.util.ReflectionUtils;
import avtas.util.WindowUtils;
import java.awt.event.ActionEvent;
import java.util.List;
import javax.swing.JFrame;
import javax.swing.JMenu;
import avtas.xml.Element;
import java.util.ArrayList;
import java.util.Collections;
import java.awt.GraphicsEnvironment;
import javax.swing.AbstractAction;
import javax.swing.JMenuBar;

/**
 * The <code>AnalysisManager</code> class collects the reports of each analysis
 * module and presents them in a GUI interface.
 *
 * @author AFRL/RQQD
 */
public class AnalysisManager extends AmasePlugin {

    List<AnalysisClient> clientList = new ArrayList<>();
    private AnalysisManager thisAnalysisMgr = this;
    int data_index = 0;

    public AnalysisManager() {
    }

    /** Read-only access for analysis exporters, including headless applications. */
    public List<AnalysisClient> getAnalysisClients() {
        return Collections.unmodifiableList(clientList);
    }

    /**
     * Gets the current analysis report for this module in XML format.
     *
     * @return The first element of the XML document representing the analysis
     * report.
     */
    public Element getAnalysisReportXML() {

        doAnalysis();

        Element topNode = new Element("AnalysisReport");
        for (AnalysisClient c : clientList) {
            Element tmp = ((AnalysisClient) c).getAnalysisReportXML();
            if (tmp != null) {
                if (tmp.getParent() != null) {
                    tmp.getParent().remove(tmp);
                }
                topNode.add(tmp);
            }
        }
        return topNode;
    }

    @Override
    public void getMenus(JMenuBar menubar) {

        JMenu analysisMenu = WindowUtils.getMenu(menubar, "Analysis");

        analysisMenu.add(new AbstractAction("Show Report") {
            @Override
            public void actionPerformed(ActionEvent e) {
                doAnalysis();
                JFrame ff = new JFrame("Analysis");
                AnalysisGUI analysisGui = new AnalysisGUI(thisAnalysisMgr);
                ff.add(analysisGui);
                ff.pack();
                ff.setVisible(true);
            }
        });

        analysisMenu.add(new AbstractAction("Run Analysis") {
            @Override
            public void actionPerformed(ActionEvent e) {
                resetAnalysis();
                doAnalysis();
            }
        });

    }

    @Override
    public void addedToApplication(Context context, Element xml, String[] cmdParams) {

        List<Element> analysisClients = XMLUtil.getChildren(xml, "Analysis/PluginList/Plugin");
        for (Element el : analysisClients) {
            try {
                Object o = ReflectionUtils.createInstance(el.getText());
                if (o instanceof AnalysisClient) {
                    if (o instanceof ContextListener) {
                        ((ContextListener) o).addedToApplication(context, xml, cmdParams);
                    }
                    clientList.add((AnalysisClient) o);
                }
            } catch (Exception ex) {
                UserExceptions.showError(this, "Error creaing Analysis Plugin", ex);
            }
        }

    }

    protected void doAnalysis() {

        final List<EventWrapper> eventList = new ArrayList<>(ScenarioState.getEventList());

        if (data_index >= eventList.size()) {
            return;
        }

        UserNotice notice = GraphicsEnvironment.isHeadless() ? null : new UserNotice("Performing Analysis", null);
        try {
            if (notice != null) notice.setVisible(true);
            for (int i = data_index; i < eventList.size(); i++) {
                if (notice != null) notice.setText("Processing Event " + i + " of " + eventList.size());
                for (AnalysisClient c : clientList) {
                    c.eventOccurred(eventList.get(i).event);
                }
            }
            data_index = eventList.size();
        } finally {
            if (notice != null) notice.dispose();
        }

    }

    protected void resetAnalysis() {
        data_index = 0;
        for (AnalysisClient c : clientList) {
            c.resetAnalysis();
        }
    }

    @Override
    public void eventOccurred(Object event) {
        if (event instanceof ScenarioEvent) {
            resetAnalysis();
        }
    }
}

/* Distribution A. Approved for public release. 
 *  Case: #88ABW-2015-4601. Date: 24 Sep 2015. */
